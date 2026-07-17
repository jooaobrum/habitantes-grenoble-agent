"""Unit tests for T6 — live health probes (infrastructure/health_checks.py).

Each probe returns the same {status, latency_ms, detail} shape and maps a
working dependency to `ok`, an unreachable one to `unreachable`, and a stale
Telegram heartbeat to `critical`. `check_openai` must ping metadata only —
never a completion endpoint — so a health check can't compound token spend.
"""

import datetime
from unittest.mock import MagicMock

from habitantes.infrastructure import health_checks


def _iso(dt: datetime.datetime) -> str:
    return dt.isoformat()


# ── check_qdrant ─────────────────────────────────────────────────────────────


def test_check_qdrant_ok(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(
        "habitantes.domain.tools.search._get_qdrant_client", lambda: client
    )

    result = health_checks.check_qdrant()

    client.get_collections.assert_called_once()
    assert result["status"] == "ok"
    assert result["latency_ms"] is not None
    assert result["detail"] is None


def test_check_qdrant_unreachable(monkeypatch):
    client = MagicMock()
    client.get_collections.side_effect = ConnectionError("connection refused")
    monkeypatch.setattr(
        "habitantes.domain.tools.search._get_qdrant_client", lambda: client
    )

    result = health_checks.check_qdrant()

    assert result["status"] == "unreachable"
    assert result["latency_ms"] is None
    assert "connection refused" in result["detail"]


# ── check_openai ─────────────────────────────────────────────────────────────


def test_check_openai_ok_and_never_calls_completion(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(health_checks, "_get_openai_client", lambda: client)

    result = health_checks.check_openai()

    model_name = load_model_name()
    client.models.retrieve.assert_called_once_with(model_name)
    # Metadata-only guarantee: no completion endpoint may be touched.
    assert not client.chat.completions.create.called
    assert not client.completions.create.called
    assert result["status"] == "ok"
    assert result["latency_ms"] is not None
    assert result["detail"] is None


def test_check_openai_unreachable(monkeypatch):
    client = MagicMock()
    client.models.retrieve.side_effect = ConnectionError("dns failure")
    monkeypatch.setattr(health_checks, "_get_openai_client", lambda: client)

    result = health_checks.check_openai()

    assert result["status"] == "unreachable"
    assert result["latency_ms"] is None
    assert "dns failure" in result["detail"]
    assert not client.chat.completions.create.called


# ── check_telegram_heartbeat ─────────────────────────────────────────────────


def test_check_telegram_heartbeat_ok():
    now = datetime.datetime.now(datetime.timezone.utc)
    store = MagicMock()
    store.read_heartbeat.return_value = {"last_seen_at": _iso(now)}

    result = health_checks.check_telegram_heartbeat(store, stale_after_seconds=180)

    assert result["status"] == "ok"
    assert result["detail"] is None


def test_check_telegram_heartbeat_stale_is_critical():
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=600)
    store = MagicMock()
    store.read_heartbeat.return_value = {"last_seen_at": _iso(old)}

    result = health_checks.check_telegram_heartbeat(store, stale_after_seconds=180)

    assert result["status"] == "critical"
    assert result["latency_ms"] is None
    assert "stale" in result["detail"]


def test_check_telegram_heartbeat_missing_is_critical():
    store = MagicMock()
    store.read_heartbeat.return_value = None

    result = health_checks.check_telegram_heartbeat(store, stale_after_seconds=180)

    assert result["status"] == "critical"
    assert result["detail"] == "no heartbeat recorded"


def load_model_name() -> str:
    from habitantes.config import load_settings

    return load_settings().llm.model_name
