import datetime
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger as loguru_logger

from habitantes.config import load_settings


@dataclass
class UsageSummary:
    """Aggregated interaction metrics over a time window (from interactions.jsonl)."""

    requests: int = 0
    cache_hits: int = 0
    cost_usd: float = 0.0
    categories: dict[str, int] = field(default_factory=dict)
    p50_ms: float = 0.0
    p95_ms: float = 0.0


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (pct in [0, 1]); empty list → 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


class InteractionLogger:
    """Helper to log every agent interaction to a structured JSONL file for traceability."""

    def __init__(self):
        settings = load_settings()
        root_dir = Path(__file__).parents[3]
        log_file = root_dir / settings.logging.interaction_path

        # Ensure log directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Configure loguru dedicated logger for interactions
        # serialize=True ensures JSON output, but we'll use a custom sink for JSONL
        self.log_file = str(log_file)
        self.logger = loguru_logger.bind(interaction=True)

        # Add sink if not already added (loguru is a singleton)
        # We use a custom format to ensure it's a pure JSON line without loguru's metadata
        loguru_logger.add(
            self.log_file,
            rotation=settings.logging.rotation,
            retention=settings.logging.retention,
            filter=lambda record: "interaction" in record["extra"],
            format="{message}",
        )

    def log_interaction(self, state: dict[str, Any]):
        """Serialize AgentState to a single JSON line."""
        # Sanitize state for logging (remove potentially large/redundant objects if needed)
        # For now, we capture everything relevant
        record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "chat_id": state.get("chat_id"),
            "message_id": state.get("message_id"),
            "trace_id": state.get("trace_id"),
            "user_query": state.get("message"),
            "intent": state.get("intent"),
            "category": state.get("category"),
            "answer": state.get("answer"),
            "confidence": state.get("confidence"),
            "cached": state.get("cached", False),
            "tokens_in": state.get("tokens_in", 0),
            "tokens_out": state.get("tokens_out", 0),
            "cost_usd": state.get("cost_usd", 0.0),
            "timings": state.get("timings"),
            "sources_count": len(state.get("sources", [])),
            # Optional: include top 3 source snippets if not too large
            "sources": [
                {"category": s.get("category"), "date": s.get("date")}
                for s in state.get("sources", [])[:3]
            ],
        }

        if state.get("error"):
            record["error"] = state["error"]

        self.logger.info(json.dumps(record, ensure_ascii=False))

    def aggregate_usage(self, since: datetime.datetime) -> UsageSummary:
        """Aggregate interaction metrics from interactions.jsonl since `since`.

        Tolerant of older lines that predate the cost fields (treated as `0`) and
        of malformed lines (skipped). A `since` in the future yields an all-zero
        summary, never an error.
        """
        summary = UsageSummary()
        log_path = Path(self.log_file)
        if not log_path.exists():
            return summary

        if since.tzinfo is None:
            since = since.replace(tzinfo=datetime.timezone.utc)

        latencies: list[float] = []
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts_raw = record.get("timestamp")
                if not ts_raw:
                    continue
                try:
                    ts = datetime.datetime.fromisoformat(ts_raw)
                except ValueError:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=datetime.timezone.utc)
                if ts < since:
                    continue

                summary.requests += 1
                if record.get("cached"):
                    summary.cache_hits += 1
                summary.cost_usd += float(record.get("cost_usd", 0.0) or 0.0)

                category = record.get("category")
                if category:
                    summary.categories[category] = (
                        summary.categories.get(category, 0) + 1
                    )

                timings = record.get("timings") or {}
                total_ms = sum(
                    float(v) for v in timings.values() if isinstance(v, (int, float))
                )
                latencies.append(total_ms)

        summary.p50_ms = _percentile(latencies, 0.5)
        summary.p95_ms = _percentile(latencies, 0.95)
        return summary


class FeedbackLogger:
    """Helper to append user thumbs-up/down feedback to a structured JSONL file."""

    def __init__(self):
        settings = load_settings()
        root_dir = Path(__file__).parents[3]
        log_file = root_dir / settings.logging.feedback_path

        # Ensure log directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)

        self.log_file = str(log_file)
        self.logger = loguru_logger.bind(feedback=True)

        loguru_logger.add(
            self.log_file,
            rotation=settings.logging.rotation,
            retention=settings.logging.retention,
            filter=lambda record: "feedback" in record["extra"],
            format="{message}",
        )

    def log_feedback(self, chat_id: str, message_id: str, rating: str, trace_id: str):
        """Serialize a single feedback event to one JSON line."""
        record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "chat_id": chat_id,
            "message_id": message_id,
            "rating": rating,
            "trace_id": trace_id,
        }
        self.logger.info(json.dumps(record, ensure_ascii=False))


# Singleton instances
_interaction_logger: InteractionLogger | None = None
_feedback_logger: FeedbackLogger | None = None


def get_interaction_logger() -> InteractionLogger:
    """Lazy factory for the InteractionLogger."""
    global _interaction_logger
    if _interaction_logger is None:
        _interaction_logger = InteractionLogger()
    return _interaction_logger


def get_feedback_logger() -> FeedbackLogger:
    """Lazy factory for the FeedbackLogger."""
    global _feedback_logger
    if _feedback_logger is None:
        _feedback_logger = FeedbackLogger()
    return _feedback_logger
