"""Background watchdog loop for the Control Center — I/O + wiring, no decisions.

Every `alerts.interval_seconds` it runs one cycle: probe the dependencies,
snapshot their health, aggregate today's cost, and — only while the switch is
still on — ask `domain/control.py` whether a threshold is breached. On a breach
it flips the switch off, appends one alert-log row, and fires one email.

The loop is edge-triggered: once the switch is off it keeps snapshotting for
dashboard freshness but never re-evaluates or re-alerts, so a standing breach
can't spam the operator.
"""

import asyncio
import datetime
import logging

from habitantes.config import load_settings
from habitantes.domain import control
from habitantes.infrastructure import control_store, health_checks
from habitantes.infrastructure.alerts.email import send_alert
from habitantes.infrastructure.logging import get_interaction_logger

logger = logging.getLogger(__name__)


def _start_of_today() -> datetime.datetime:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _cost_today_usd() -> float:
    return get_interaction_logger().aggregate_usage(_start_of_today()).cost_usd


def run_watchdog_cycle(db_path=control_store.DEFAULT_DB_PATH) -> None:
    """Run a single probe → snapshot → aggregate → evaluate → act cycle."""
    # 1. Probe every dependency and snapshot it — always, regardless of switch state.
    probes = {
        "qdrant": health_checks.check_qdrant(),
        "openai": health_checks.check_openai(),
        "telegram_bot": health_checks.check_telegram_heartbeat(control_store),
    }
    prior = {row["service"]: row for row in control_store.read_health_snapshot(db_path)}
    streaks: dict[str, int] = {}
    for service, result in probes.items():
        healthy = result["status"] == "ok"
        prev = prior.get(service, {}).get("consecutive_failures", 0)
        failures = 0 if healthy else prev + 1
        streaks[service] = failures
        control_store.write_health_snapshot(
            service=service,
            status=result["status"],
            latency_ms=result["latency_ms"],
            consecutive_failures=failures,
            detail=result["detail"],
            db_path=db_path,
        )

    # 2. Aggregate today's estimated cost from the interaction log.
    cost_today = _cost_today_usd()

    # 3. Already in the safe state → nothing to evaluate or spam. Edge-triggered.
    switch = control_store.get_switch(db_path)
    if not switch["enabled"]:
        logger.info(
            "watchdog: switch already off, snapshot-only cycle (cost_today=$%.4f)",
            cost_today,
        )
        return

    # 4. Evaluate thresholds (pure) and act on the first breach.
    thresholds_row = control_store.get_thresholds(db_path)
    thresholds = control.ThresholdsSnapshot(
        daily_cost_limit_usd=thresholds_row["daily_cost_limit_usd"],
        health_grace_checks=thresholds_row["health_grace_checks"],
        auto_disable_enabled=thresholds_row["auto_disable_enabled"],
        email_to=thresholds_row["email_to"],
        monthly_budget_usd=thresholds_row["monthly_budget_usd"],
    )
    breach = control.evaluate_thresholds(cost_today, streaks, thresholds)

    if breach is None:
        logger.info("watchdog: healthy cycle, no breach (cost_today=$%.4f)", cost_today)
        return

    if not thresholds.auto_disable_enabled:
        logger.error(
            "watchdog: breach %s (%s) but auto-disable is off — logged only",
            breach.trigger,
            breach.measured,
        )
        return

    # Flip the switch off first; the email is best-effort after (spec Failure modes).
    control_store.set_switch(False, changed_by=breach.changed_by, db_path=db_path)
    email_sent = send_alert(
        subject=f"[Habitantes] Bot disabled: {breach.trigger}",
        body=(
            f"The Control Center disabled the bot.\n\n"
            f"Trigger: {breach.trigger}\nMeasured: {breach.measured}\n"
        ),
    )
    control_store.append_alert(
        trigger=breach.trigger,
        measured=breach.measured,
        action="switch_disabled",
        email_sent=email_sent,
        status="active",
        db_path=db_path,
    )
    logger.error(
        "watchdog: breach %s (%s) — switch disabled, email_sent=%s",
        breach.trigger,
        breach.measured,
        email_sent,
    )


async def watchdog_loop(db_path=control_store.DEFAULT_DB_PATH) -> None:
    """Run `run_watchdog_cycle` forever on the configured interval.

    The cycle does blocking I/O (SQLite, HTTP pings, SMTP), so it runs in a
    worker thread to keep the API event loop responsive.
    """
    interval = load_settings().alerts.interval_seconds
    while True:
        try:
            await asyncio.to_thread(run_watchdog_cycle, db_path)
        except Exception:
            logger.exception("watchdog cycle raised — continuing")
        await asyncio.sleep(interval)
