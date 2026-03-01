"""Domain nodes — pure functions for the LangGraph agent graph.

Each node signature: (AgentState) -> dict  (partial state update)
No side effects, no global mutable state. LLM calls use a lazy factory.
"""

import json
import logging
import time

from habitantes.domain.prompts.intent import build_intent_messages
from habitantes.domain.prompts.synthesis import build_synthesis_messages
from habitantes.domain.state import AgentState

logger = logging.getLogger(__name__)

# ── Static responses (Portuguese) ────────────────────────────────────────────

_DECLINE_RESPONSE = (
    "Desculpe, só consigo ajudar com perguntas relacionadas à vida de expatriados em Grenoble. "
    "Se tiver dúvidas sobre visto, moradia, saúde, transporte ou outro tema da vida em Grenoble, "
    "ficarei feliz em ajudar!"
)

_CLARIFICATION_RESPONSE = (
    "Sua pergunta está um pouco ampla. Poderia dar mais detalhes?\n\n"
    "Por exemplo: qual aspecto específico você gostaria de saber? "
    "Isso me ajudará a encontrar a informação mais relevante para você."
)

_FEEDBACK_RESPONSE = "Obrigado pelo seu feedback! Isso nos ajuda a melhorar."

_NO_RESULTS_FALLBACK = "Não encontrei informações confiáveis sobre este tema."


# ── Lazy greeting text (built once from config) ───────────────────────────────

_greeting_text: str | None = None


def _get_greeting_text() -> str:
    global _greeting_text
    if _greeting_text is None:
        from habitantes.config import load_settings
        from habitantes.domain.categories import build_greeting_text

        _greeting_text = build_greeting_text(load_settings().categories)
    return _greeting_text


# ── LLM factory (lazy, never crashes on import) ───────────────────────────────

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        from langchain_openai import ChatOpenAI

        from habitantes.config import load_settings

        settings = load_settings()
        _llm = ChatOpenAI(
            model=settings.llm.model_name,
            api_key=settings.llm.openai_api_key,
            temperature=0,
        )
    return _llm


# ── Helper ────────────────────────────────────────────────────────────────────


def _merge_timings(state: AgentState, key: str, elapsed_ms: float) -> dict[str, float]:
    current = state.get("timings") or {}
    return {**current, key: elapsed_ms}


# ── Nodes ─────────────────────────────────────────────────────────────────────


def classify_intent(state: AgentState) -> dict:
    """Classify message intent via LLM.

    Short-circuits to qa+category when the message is a category number (no LLM call).

    Returns: {intent, timings} or {intent, category, timings}
    """
    t0 = time.monotonic()

    # Number shortcut: resolve "1"–"19" directly without calling the LLM
    from habitantes.domain.categories import _get_categories, resolve_number

    cat = resolve_number(state["message"], _get_categories())
    if cat:
        return {
            "intent": "qa",
            "category": cat.en_name,
            "timings": _merge_timings(
                state, "intent_ms", (time.monotonic() - t0) * 1000
            ),
        }

    llm = _get_llm()
    messages = build_intent_messages(state["message"], history=state.get("history"))
    response = llm.invoke(messages)

    try:
        data = json.loads(response.content)
        intent = data.get("intent", "out_of_scope")
    except (json.JSONDecodeError, AttributeError):
        logger.warning(
            "Failed to parse intent JSON",
            extra={
                "trace_id": state.get("trace_id"),
                "raw": getattr(response, "content", ""),
            },
        )
        intent = "out_of_scope"

    return {
        "intent": intent,
        "timings": _merge_timings(state, "intent_ms", (time.monotonic() - t0) * 1000),
    }


def route(state: AgentState) -> str:
    """Conditional edge: decide retrieval strategy based on message length.

    Returns: 'rag' | 'clarify'
    """
    message = state.get("message", "")
    if len(message.strip()) < 10:
        return "clarify"
    return "rag"


def generate_response(state: AgentState) -> dict:
    """Generate grounded answer from retrieved context chunks via LLM.

    Returns: {answer, sources, confidence, timings}
    """
    t0 = time.monotonic()
    chunks = state.get("context_chunks") or []

    if not chunks:
        logger.info(
            "No context chunks — returning fallback",
            extra={"trace_id": state.get("trace_id")},
        )
        return {
            "answer": _NO_RESULTS_FALLBACK,
            "sources": [],
            "confidence": 0.0,
            "timings": _merge_timings(
                state, "generation_ms", (time.monotonic() - t0) * 1000
            ),
        }

    llm = _get_llm()
    messages = build_synthesis_messages(
        state["message"],
        chunks,
        history=state.get("history"),
    )
    response = llm.invoke(messages)

    sources = [
        {
            "text_snippet": (chunk.get("text") or chunk.get("answer", ""))[:200],
            "date": chunk.get("date", ""),
            "category": chunk.get("category", ""),
        }
        for chunk in chunks
    ]

    top_score = max((c.get("score", 0.0) for c in chunks), default=0.0)
    confidence = min(1.0, float(top_score))

    return {
        "answer": response.content,
        "sources": sources,
        "confidence": confidence,
        "timings": _merge_timings(
            state, "generation_ms", (time.monotonic() - t0) * 1000
        ),
    }


def generate_greeting(state: AgentState) -> dict:
    """Return greeting with numbered category menu (built from config).

    Returns: {answer, confidence}
    """
    return {"answer": _get_greeting_text(), "confidence": 1.0}


def generate_decline(state: AgentState) -> dict:
    """Return out-of-scope decline response.

    Returns: {answer, confidence}
    """
    return {"answer": _DECLINE_RESPONSE, "confidence": 1.0}


def generate_clarification(state: AgentState) -> dict:
    """Return clarification request.

    When a category was already selected (state has en_name), the response
    names the Portuguese category so the user knows what context is active.

    Returns: {answer, confidence}
    """
    category_en = state.get("category", "")
    if category_en:
        from habitantes.domain.categories import _get_categories, get_by_en_name

        entry = get_by_en_name(category_en, _get_categories())
        pt_name = entry.pt_name if entry else category_en
        answer = (
            f"Ótimo! Você escolheu *{pt_name}*. " "Qual é a sua dúvida sobre este tema?"
        )
    else:
        answer = _CLARIFICATION_RESPONSE
    return {"answer": answer, "confidence": 0.5}


def log_feedback(state: AgentState) -> dict:
    """Log user feedback and return acknowledgment.

    Returns: {answer}
    """
    logger.info(
        "Feedback received",
        extra={
            "trace_id": state.get("trace_id", ""),
            "chat_id": state.get("chat_id", ""),
            "message_id": state.get("message_id", ""),
            "message": state.get("message", ""),
        },
    )
    return {"answer": _FEEDBACK_RESPONSE}
