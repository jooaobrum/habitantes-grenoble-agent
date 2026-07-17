"""Unit tests for T5 — InteractionLogger.aggregate_usage (logging.py).

Aggregation reads logs/interactions.jsonl, tolerating older lines that predate
the cost fields (treated as 0). A `since` in the future yields an all-zero
summary rather than an error.
"""

import datetime
import json

import pytest

from habitantes.infrastructure.logging import InteractionLogger


def _iso(dt: datetime.datetime) -> str:
    return dt.isoformat()


@pytest.fixture
def logger_with_fixture(tmp_path):
    """An InteractionLogger pointed at a fixture JSONL of mixed-format lines."""
    now = datetime.datetime.now(datetime.timezone.utc)
    recent = now - datetime.timedelta(hours=1)

    lines = [
        # Old-format line: no tokens_in/out/cost_usd fields at all.
        {
            "timestamp": _iso(recent),
            "category": "visa",
            "cached": False,
            "timings": {"intent_ms": 10, "react_ms": 90},
        },
        # New-format line: full cost fields, cache hit.
        {
            "timestamp": _iso(recent),
            "category": "visa",
            "cached": True,
            "tokens_in": 100,
            "tokens_out": 50,
            "cost_usd": 0.002,
            "timings": {"intent_ms": 5, "react_ms": 45},
        },
        # New-format line: different category.
        {
            "timestamp": _iso(recent),
            "category": "housing",
            "cached": False,
            "tokens_in": 200,
            "tokens_out": 80,
            "cost_usd": 0.003,
            "timings": {"intent_ms": 20, "react_ms": 80},
        },
    ]

    fixture = tmp_path / "interactions.jsonl"
    fixture.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )

    logger = InteractionLogger()
    logger.log_file = str(fixture)
    return logger


def test_aggregate_mixed_format_lines(logger_with_fixture):
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    summary = logger_with_fixture.aggregate_usage(since)

    assert summary.requests == 3
    assert summary.cache_hits == 1
    # Old-format line contributes 0 cost; new lines sum to 0.005.
    assert summary.cost_usd == pytest.approx(0.005)
    assert summary.categories == {"visa": 2, "housing": 1}
    # Latencies: [100, 50, 100] → p50 = 100, p95 = 100.
    assert summary.p50_ms == pytest.approx(100.0)
    assert summary.p95_ms == pytest.approx(100.0)


def test_since_in_future_returns_all_zero(logger_with_fixture):
    since = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    summary = logger_with_fixture.aggregate_usage(since)

    assert summary.requests == 0
    assert summary.cache_hits == 0
    assert summary.cost_usd == 0.0
    assert summary.categories == {}
    assert summary.p50_ms == 0.0
    assert summary.p95_ms == 0.0
