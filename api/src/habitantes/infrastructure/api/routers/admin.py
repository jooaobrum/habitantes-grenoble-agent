"""Control Center admin API — token-gated read/write over the control store.

Wires the pure decision logic (`domain/control.py`) and the I/O wrappers
(`control_store`, `health_checks`, `alerts.email`, `logging`) behind a single
`ADMIN_TOKEN` dependency. No business logic here beyond assembling the response
contracts defined in `domain/schemas.py`.
"""

import datetime
import hmac
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, status

from habitantes.config import load_settings
from habitantes.domain.schemas import (
    AdminStatusResponse,
    AlertEntry,
    CategoryCount,
    HeartbeatRequest,
    Kpis,
    ServiceStatus,
    SwitchRequest,
    SwitchResponse,
    SwitchStatus,
    TestAlertResponse,
    ThresholdsRequest,
    ThresholdsState,
)
from habitantes.infrastructure import control_store
from habitantes.infrastructure.alerts.email import send_alert
from habitantes.infrastructure.logging import get_interaction_logger

logger = logging.getLogger(__name__)


def require_admin_token(
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
) -> None:
    """Reject any request whose `X-Admin-Token` doesn't match `settings.admin.token`.

    Uses `hmac.compare_digest` (constant-time, no timing side-channel) and never
    logs the token itself.
    """
    expected = load_settings().admin.token
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        logger.warning("admin: rejected request with invalid/missing token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
        )


def get_control_db_path() -> Path:
    """Resolve the control-store path at request time.

    A dependency (not a default arg) so tests can point every route at a
    throwaway SQLite db via `app.dependency_overrides`.
    """
    return control_store.DEFAULT_DB_PATH


router = APIRouter(dependencies=[Depends(require_admin_token)])


def _start_of_today() -> datetime.datetime:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month() -> datetime.datetime:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


_FALLBACK_THRESHOLDS = {
    "daily_cost_limit_usd": 0.0,
    "health_grace_checks": 0,
    "email_to": "",
    "auto_disable_enabled": False,
    "monthly_budget_usd": 0.0,
}


@router.get("/status", response_model=AdminStatusResponse)
def get_status(db_path: Path = Depends(get_control_db_path)) -> AdminStatusResponse:
    """Assemble the dashboard payload from already-persisted state — no live pings.

    Everything here was written by the watchdog or the interaction log, keeping
    this path off the external network so it stays inside the spec's 800ms p95.

    Fail-open (spec Safety): `control_store` can't record its own failure in a
    table it can't write to, so a broken read is caught right here and reported
    as a synthetic `critical` service row instead — the one place this failure
    can surface, since the chat path (`control_store.is_enabled`) only fails
    open silently.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        switch = control_store.get_switch(db_path)
        thresholds = control_store.get_thresholds(db_path)
        snapshots = control_store.read_health_snapshot(db_path)
        alerts = control_store.read_alerts(db_path=db_path)
        control_store_critical = False
    except Exception:
        logger.error("admin: control store unreadable", exc_info=True)
        switch = {"enabled": True, "changed_at": now}
        thresholds = _FALLBACK_THRESHOLDS
        snapshots = []
        alerts = []
        control_store_critical = True

    interactions = get_interaction_logger()
    today = interactions.aggregate_usage(_start_of_today())
    month = interactions.aggregate_usage(_start_of_month())

    services = [
        ServiceStatus(
            name=row["service"],
            status=row["status"],
            latency_ms=row["latency_ms"],
            checked_at=row["checked_at"],
        )
        for row in snapshots
    ]
    if control_store_critical:
        services.append(
            ServiceStatus(
                name="control_store",
                status="critical",
                latency_ms=None,
                checked_at=now,
            )
        )
    ok_count = sum(1 for row in snapshots if row["status"] == "ok")
    uptime_24h_pct = round(100.0 * ok_count / len(snapshots), 1) if snapshots else 100.0

    cache_hit_rate = (
        round(today.cache_hits / today.requests, 3) if today.requests else 0.0
    )

    categories = [
        CategoryCount(name=name, count=count)
        for name, count in sorted(
            today.categories.items(), key=lambda kv: kv[1], reverse=True
        )
    ]

    return AdminStatusResponse(
        switch=SwitchStatus(enabled=switch["enabled"], changed_at=switch["changed_at"]),
        services=services,
        kpis=Kpis(
            requests_today=today.requests,
            cache_hit_rate=cache_hit_rate,
            cost_today_usd=round(today.cost_usd, 4),
            cost_month_usd=round(month.cost_usd, 4),
            budget_daily_usd=thresholds["daily_cost_limit_usd"],
            budget_monthly_usd=thresholds["monthly_budget_usd"],
            uptime_24h_pct=uptime_24h_pct,
        ),
        categories=categories,
        thresholds=ThresholdsState(
            daily_cost_limit_usd=thresholds["daily_cost_limit_usd"],
            health_grace_checks=thresholds["health_grace_checks"],
            email_to=thresholds["email_to"],
            auto_disable_enabled=thresholds["auto_disable_enabled"],
            monthly_budget_usd=thresholds["monthly_budget_usd"],
        ),
        alerts=[
            AlertEntry(
                timestamp=row["timestamp"],
                trigger=row["trigger"],
                measured=row["measured"],
                action=row["action"],
                status=row["status"],
            )
            for row in alerts
        ],
    )


@router.post("/switch", response_model=SwitchResponse)
def post_switch(
    body: SwitchRequest, db_path: Path = Depends(get_control_db_path)
) -> SwitchResponse:
    """Toggle the kill switch. Re-enabling resolves every open alert (design's
    Resolution rule) — the one deliberate place resolution happens."""
    updated = control_store.set_switch(
        body.enabled, changed_by="admin", db_path=db_path
    )
    if body.enabled:
        control_store.resolve_open_alerts(db_path)
        control_store.append_alert(
            trigger="manual:switch_on",
            measured=None,
            action="switch_enabled",
            status="resolved",
            db_path=db_path,
        )
    else:
        control_store.append_alert(
            trigger="manual:switch_off",
            measured=None,
            action="switch_disabled",
            status="active",
            db_path=db_path,
        )
    logger.info("admin: switch set to enabled=%s", body.enabled)
    return SwitchResponse(enabled=updated["enabled"], changed_at=updated["changed_at"])


@router.post("/thresholds", response_model=ThresholdsState)
def post_thresholds(
    body: ThresholdsRequest, db_path: Path = Depends(get_control_db_path)
) -> ThresholdsState:
    """Persist edited thresholds. `monthly_budget_usd` is display-only (design)
    so it's preserved from the existing row, not taken from the request body."""
    current = control_store.get_thresholds(db_path)
    updated = control_store.set_thresholds(
        daily_cost_limit_usd=body.daily_cost_limit_usd,
        health_grace_checks=body.health_grace_checks,
        email_to=body.email_to,
        auto_disable_enabled=body.auto_disable_enabled,
        monthly_budget_usd=current["monthly_budget_usd"],
        db_path=db_path,
    )
    control_store.append_alert(
        trigger="thresholds_updated",
        measured=None,
        action="thresholds_updated",
        status="resolved",
        db_path=db_path,
    )
    logger.info("admin: thresholds updated")
    return ThresholdsState(
        daily_cost_limit_usd=updated["daily_cost_limit_usd"],
        health_grace_checks=updated["health_grace_checks"],
        email_to=updated["email_to"],
        auto_disable_enabled=updated["auto_disable_enabled"],
        monthly_budget_usd=updated["monthly_budget_usd"],
    )


@router.post("/heartbeat")
def post_heartbeat(
    body: HeartbeatRequest, db_path: Path = Depends(get_control_db_path)
) -> dict[str, str]:
    """Called by the Telegram bot on its own poll loop. Reuses `ADMIN_TOKEN` as
    the service-to-service secret — no second credential to manage."""
    control_store.touch_heartbeat(body.service, db_path)
    return {"status": "ok", "service": body.service}


@router.post("/test-alert", response_model=TestAlertResponse)
def post_test_alert(
    db_path: Path = Depends(get_control_db_path),
) -> TestAlertResponse:
    """Send a test email and log it as an immediately-resolved row. Never touches
    the switch."""
    email_sent = send_alert(
        subject="[Habitantes] Control Center test alert",
        body="This is a test alert from the Control Center. No action was taken.",
    )
    control_store.append_alert(
        trigger="test_alert",
        measured=None,
        action="test_email_sent",
        email_sent=email_sent,
        status="resolved",
        db_path=db_path,
    )
    detail = "Test email sent" if email_sent else "Email not sent (check SMTP config)"
    logger.info("admin: test alert email_sent=%s", email_sent)
    return TestAlertResponse(email_sent=email_sent, detail=detail)
