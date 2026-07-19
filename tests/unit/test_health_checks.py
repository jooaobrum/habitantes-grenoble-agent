"""Unit tests for T6 — live health probes (infrastructure/health_checks.py).

Each probe returns the same {status, latency_ms, detail} shape and maps a
working dependency to `ok`, an unreachable one to `unreachable`, and a stale
bot heartbeat to `critical`. `check_openrouter` (the chat provider) and
`check_openai_embeddings` (the real OpenAI API used for embeddings) must each
ping metadata only — a `models.list`, never a completion/embedding endpoint —
so a health check can't compound token spend.
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


# ── check_openrouter ─────────────────────────────────────────────────────────


def test_check_openrouter_ok_and_never_calls_completion(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(health_checks, "_get_openrouter_client", lambda: client)

    result = health_checks.check_openrouter()

    # OpenRouter has no reliable per-model retrieve; a zero-token `models.list`
    # is the metadata-only probe.
    client.models.list.assert_called_once_with()
    # Metadata-only guarantee: no completion endpoint may be touched.
    assert not client.chat.completions.create.called
    assert not client.completions.create.called
    assert result["status"] == "ok"
    assert result["latency_ms"] is not None
    assert result["detail"] is None


def test_check_openrouter_unreachable(monkeypatch):
    client = MagicMock()
    client.models.list.side_effect = ConnectionError("dns failure")
    monkeypatch.setattr(health_checks, "_get_openrouter_client", lambda: client)

    result = health_checks.check_openrouter()

    assert result["status"] == "unreachable"
    assert result["latency_ms"] is None
    assert "dns failure" in result["detail"]
    assert not client.chat.completions.create.called


# ── check_openai_embeddings ──────────────────────────────────────────────────


def test_check_openai_embeddings_ok_and_never_calls_embeddings(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(health_checks, "_get_openai_embeddings_client", lambda: client)

    result = health_checks.check_openai_embeddings()

    # Metadata-only guarantee: no embeddings call may be touched.
    client.models.list.assert_called_once_with()
    assert not client.embeddings.create.called
    assert result["status"] == "ok"
    assert result["latency_ms"] is not None
    assert result["detail"] is None


def test_check_openai_embeddings_unreachable(monkeypatch):
    client = MagicMock()
    client.models.list.side_effect = ConnectionError("dns failure")
    monkeypatch.setattr(health_checks, "_get_openai_embeddings_client", lambda: client)

    result = health_checks.check_openai_embeddings()

    assert result["status"] == "unreachable"
    assert result["latency_ms"] is None
    assert "dns failure" in result["detail"]
    assert not client.embeddings.create.called


# ── check_heartbeat ──────────────────────────────────────────────────────────


def test_check_heartbeat_ok():
    now = datetime.datetime.now(datetime.timezone.utc)
    store = MagicMock()
    store.read_heartbeat.return_value = {"last_seen_at": _iso(now)}

    result = health_checks.check_heartbeat(
        "telegram_bot", store, stale_after_seconds=180
    )

    store.read_heartbeat.assert_called_once_with("telegram_bot")
    assert result["status"] == "ok"
    assert result["detail"] is None


def test_check_heartbeat_stale_is_critical():
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=600)
    store = MagicMock()
    store.read_heartbeat.return_value = {"last_seen_at": _iso(old)}

    result = health_checks.check_heartbeat(
        "whatsapp_bot", store, stale_after_seconds=180
    )

    assert result["status"] == "critical"
    assert result["latency_ms"] is None
    assert "stale" in result["detail"]


def test_check_heartbeat_missing_is_critical():
    store = MagicMock()
    store.read_heartbeat.return_value = None

    result = health_checks.check_heartbeat(
        "whatsapp_bot", store, stale_after_seconds=180
    )

    assert result["status"] == "critical"
    assert result["detail"] == "no heartbeat recorded"
