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

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI

        from habitantes.config import load_settings

        _openai_client = OpenAI(api_key=load_settings().llm.openai_api_key)
    return _openai_client


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


def check_openai() -> dict[str, Any]:
    """Ping OpenAI with a metadata-only `models.retrieve` — no completion, zero tokens."""
    from habitantes.config import load_settings

    model_name = load_settings().llm.model_name
    start = time.perf_counter()
    try:
        client = _get_openai_client()
        client.models.retrieve(model_name)
    except Exception as exc:
        return {"status": "unreachable", "latency_ms": None, "detail": str(exc)[:200]}
    return {"status": "ok", "latency_ms": _elapsed_ms(start), "detail": None}


def check_telegram_heartbeat(
    store: Any, stale_after_seconds: float | None = None
) -> dict[str, Any]:
    """Report `ok` if the bot's heartbeat is fresh, `critical` if stale or missing.

    The bot posts a heartbeat on its own poll loop; if we haven't heard from it
    within `stale_after_seconds` it's presumed down. The default staleness bound
    is `3 × alerts.interval_seconds` (three missed cycles) so a single late post
    doesn't flip the status — config stays the single source of truth.
    """
    if stale_after_seconds is None:
        from habitantes.config import load_settings

        stale_after_seconds = load_settings().alerts.interval_seconds * 3

    record = store.read_heartbeat()
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
