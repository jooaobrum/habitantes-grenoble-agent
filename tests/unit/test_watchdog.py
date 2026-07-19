"""Unit tests for T8 — watchdog cycle (infrastructure/alerts/watchdog.py).

One cycle probes, snapshots, aggregates cost, and acts on a breach. Asserts:
(a) the health snapshot is always written; (b) no alert/email under both limits;
(c) exactly one alert row + one email attempt on a breach, with the switch off;
(d) a second cycle with the switch already off is snapshot-only — no re-alert,
no re-email (edge-triggered).
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from habitantes.infrastructure import control_store as cs
from habitantes.infrastructure import health_checks
from habitantes.infrastructure.alerts import watchdog


@pytest.fixture
def db_path():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "control.db"
        cs.init_db(path)
        yield path


def _all_ok(monkeypatch):
    ok = {"status": "ok", "latency_ms": 1.0, "detail": None}
    monkeypatch.setattr(health_checks, "check_qdrant", lambda: dict(ok))
    monkeypatch.setattr(health_checks, "check_openrouter", lambda: dict(ok))
    monkeypatch.setattr(health_checks, "check_openai_embeddings", lambda: dict(ok))
    monkeypatch.setattr(
        health_checks, "check_heartbeat", lambda service, store: dict(ok)
    )


def _set_cost(monkeypatch, cost):
    logger = SimpleNamespace(
        aggregate_usage=lambda since: SimpleNamespace(cost_usd=cost)
    )
    monkeypatch.setattr(watchdog, "get_interaction_logger", lambda: logger)


def test_snapshot_always_written_and_no_alert_under_limits(monkeypatch, db_path):
    _all_ok(monkeypatch)
    _set_cost(monkeypatch, cost=1.0)  # under default 5.0 limit
    email = MagicMock(return_value=True)
    monkeypatch.setattr(watchdog, "send_alert", email)

    watchdog.run_watchdog_cycle(db_path)

    # (a) snapshot always written — one row per probed service
    snapshots = {r["service"]: r for r in cs.read_health_snapshot(db_path)}
    assert set(snapshots) == {
        "qdrant",
        "openrouter",
        "openai",
        "telegram_bot",
        "whatsapp_bot",
    }
    assert all(r["status"] == "ok" for r in snapshots.values())

    # (b) no alert, no email, switch untouched
    assert cs.read_alerts(db_path=db_path) == []
    email.assert_not_called()
    assert cs.get_switch(db_path)["enabled"] is True


def test_cost_breach_disables_switch_once_and_is_edge_triggered(monkeypatch, db_path):
    _all_ok(monkeypatch)
    _set_cost(monkeypatch, cost=9.99)  # over default 5.0 limit
    email = MagicMock(return_value=True)
    monkeypatch.setattr(watchdog, "send_alert", email)

    # (c) first cycle: breach → one alert row, one email, switch off
    watchdog.run_watchdog_cycle(db_path)

    alerts = cs.read_alerts(db_path=db_path)
    assert len(alerts) == 1
    assert alerts[0]["trigger"] == "daily_cost_limit_breach"
    assert alerts[0]["action"] == "switch_disabled"
    assert alerts[0]["email_sent"] == 1
    assert email.call_count == 1

    switch = cs.get_switch(db_path)
    assert switch["enabled"] is False
    assert switch["changed_by"] == "watchdog:daily_cost_limit"

    # (d) second cycle with switch still off: snapshot-only, no re-alert/re-email
    watchdog.run_watchdog_cycle(db_path)

    assert len(cs.read_alerts(db_path=db_path)) == 1
    assert email.call_count == 1
    # snapshot still refreshed while off
    assert len(cs.read_health_snapshot(db_path)) == 5


def test_health_breach_disables_switch_after_grace(monkeypatch, db_path):
    fail = {"status": "unreachable", "latency_ms": None, "detail": "down"}
    ok = {"status": "ok", "latency_ms": 1.0, "detail": None}
    monkeypatch.setattr(health_checks, "check_qdrant", lambda: dict(ok))
    monkeypatch.setattr(health_checks, "check_openrouter", lambda: dict(fail))
    monkeypatch.setattr(health_checks, "check_openai_embeddings", lambda: dict(ok))
    monkeypatch.setattr(
        health_checks, "check_heartbeat", lambda service, store: dict(ok)
    )
    _set_cost(monkeypatch, cost=0.0)
    email = MagicMock(return_value=True)
    monkeypatch.setattr(watchdog, "send_alert", email)

    # Default grace = 3: two cycles below grace, third trips the breach.
    watchdog.run_watchdog_cycle(db_path)
    watchdog.run_watchdog_cycle(db_path)
    assert cs.get_switch(db_path)["enabled"] is True
    assert cs.read_alerts(db_path=db_path) == []

    watchdog.run_watchdog_cycle(db_path)

    switch = cs.get_switch(db_path)
    assert switch["enabled"] is False
    assert switch["changed_by"] == "watchdog:health:openrouter"
    alerts = cs.read_alerts(db_path=db_path)
    assert len(alerts) == 1
    assert alerts[0]["trigger"] == "health:openrouter"
    assert email.call_count == 1


def test_email_failure_still_disables_switch(monkeypatch, db_path):
    _all_ok(monkeypatch)
    _set_cost(monkeypatch, cost=9.99)
    monkeypatch.setattr(watchdog, "send_alert", MagicMock(return_value=False))

    watchdog.run_watchdog_cycle(db_path)

    assert cs.get_switch(db_path)["enabled"] is False
    alerts = cs.read_alerts(db_path=db_path)
    assert len(alerts) == 1
    assert alerts[0]["email_sent"] == 0
