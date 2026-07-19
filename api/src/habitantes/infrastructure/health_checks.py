"""Live health probes for the Control Center — pure I/O, no decisions.

Each probe pings one dependency and returns the same shape so they're
interchangeable and easy to snapshot:

    {"status": str, "latency_ms": float | None, "detail": str | None}

`status` is one of `ok` | `critical` | `unreachable`. The decision of what to do
with a failing probe (increment a streak, disable the switch) lives in the
watchdog and `domain/control.py`, never here.
"""

import datetime
import time
from typing import Any

_openrouter_client = None
_openai_embeddings_client = None


def _get_openrouter_client():
    global _openrouter_client
    if _openrouter_client is None:
        from openai import OpenAI

        from habitantes.config import load_settings

        settings = load_settings()
        # Chat runs through OpenRouter (OpenAI-API-compatible), a separate
        # credential/host from the real OpenAI API used for embeddings below.
        _openrouter_client = OpenAI(
            api_key=settings.llm.openrouter_api_key,
            base_url=settings.llm.base_url,
        )
    return _openrouter_client


def _get_openai_embeddings_client():
    global _openai_embeddings_client
    if _openai_embeddings_client is None:
        from openai import OpenAI

        from habitantes.config import load_settings

        settings = load_settings()
        # Embeddings stay on the real OpenAI API (OpenRouter has no embeddings
        # endpoint) — see domain/tools/_embedding.py. Same host as production.
        _openai_embeddings_client = OpenAI(api_key=settings.llm.openai_api_key)
    return _openai_embeddings_client


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def check_qdrant() -> dict[str, Any]:
    """Ping Qdrant with the same cheap `get_collections()` call `/health` uses."""
    from habitantes.domain.tools.search import _get_qdrant_client

    start = time.perf_counter()
    try:
        client = _get_qdrant_client()
        client.get_collections()
    except Exception as exc:
        return {"status": "unreachable", "latency_ms": None, "detail": str(exc)[:200]}
    return {"status": "ok", "latency_ms": _elapsed_ms(start), "detail": None}


def check_openrouter() -> dict[str, Any]:
    """Ping the chat LLM provider (OpenRouter) with a metadata-only `models.list`
    — no completion, zero tokens. `models.retrieve(id)` is unreliable on
    OpenRouter, so we list instead."""
    start = time.perf_counter()
    try:
        client = _get_openrouter_client()
        client.models.list()
    except Exception as exc:
        return {"status": "unreachable", "latency_ms": None, "detail": str(exc)[:200]}
    return {"status": "ok", "latency_ms": _elapsed_ms(start), "detail": None}


def check_openai_embeddings() -> dict[str, Any]:
    """Ping the real OpenAI API used for embeddings (`domain/tools/_embedding.py`)
    with a metadata-only `models.list` — no embedding call, zero tokens. Separate
    credential/host from OpenRouter, so it needs its own probe."""
    start = time.perf_counter()
    try:
        client = _get_openai_embeddings_client()
        client.models.list()
    except Exception as exc:
        return {"status": "unreachable", "latency_ms": None, "detail": str(exc)[:200]}
    return {"status": "ok", "latency_ms": _elapsed_ms(start), "detail": None}


def check_heartbeat(
    service: str, store: Any, stale_after_seconds: float | None = None
) -> dict[str, Any]:
    """Report `ok` if `service`'s heartbeat is fresh, `critical` if stale or missing.

    Each bot (Telegram, WhatsApp) posts a heartbeat on its own poll loop; if we
    haven't heard from it within `stale_after_seconds` it's presumed down. The
    default staleness bound is `3 × alerts.interval_seconds` (three missed
    cycles) so a single late post doesn't flip the status — config stays the
    single source of truth.
    """
    if stale_after_seconds is None:
        from habitantes.config import load_settings

        stale_after_seconds = load_settings().alerts.interval_seconds * 3

    record = store.read_heartbeat(service)
    if not record or not record.get("last_seen_at"):
        return {
            "status": "critical",
            "latency_ms": None,
            "detail": "no heartbeat recorded",
        }

    try:
        last_seen = datetime.datetime.fromisoformat(record["last_seen_at"])
    except ValueError:
        return {
            "status": "critical",
            "latency_ms": None,
            "detail": "unparseable heartbeat timestamp",
        }
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=datetime.timezone.utc)

    age_seconds = (
        datetime.datetime.now(datetime.timezone.utc) - last_seen
    ).total_seconds()
    if age_seconds > stale_after_seconds:
        return {
            "status": "critical",
            "latency_ms": None,
            "detail": f"heartbeat stale by {int(age_seconds)}s",
        }
    return {"status": "ok", "latency_ms": round(age_seconds * 1000, 2), "detail": None}
