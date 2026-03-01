from typing import TypedDict


class AgentState(TypedDict):
    """Typed state passed through the LangGraph graph."""

    # ── Request context ──
    chat_id: str
    message: str
    message_id: str
    trace_id: str

    # ── Classification ──
    intent: str  # greeting | qa | feedback | out_of_scope
    category: str  # visa | housing | healthcare | banking | transport | education | caf | general

    # ── Retrieval ──
    context_chunks: list[dict]  # [{text, source, date, category, score}]

    # ── Response ──
    answer: str
    sources: list[dict]  # [{text_snippet, date, category}]
    confidence: float

    # ── Memory ──
    history: list[dict]  # last 5 messages [{role, content}]

    # ── Observability ──
    timings: dict[str, float]  # {intent_ms, category_ms, search_ms, generation_ms}
    error: dict | None  # {error_code, message, retryable} or None
