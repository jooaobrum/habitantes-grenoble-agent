import datetime
import json
from pathlib import Path
from typing import Any

from loguru import logger as loguru_logger

from habitantes.config import load_settings


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


# Singleton instance
_interaction_logger: InteractionLogger | None = None


def get_interaction_logger() -> InteractionLogger:
    """Lazy factory for the InteractionLogger."""
    global _interaction_logger
    if _interaction_logger is None:
        _interaction_logger = InteractionLogger()
    return _interaction_logger
