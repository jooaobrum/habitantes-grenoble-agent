"""Agent graph — LangGraph StateGraph wiring all domain nodes and tools.

Graph topology (per design.md):

    START → classify_intent
              ├── greeting      → generate_greeting      → END
              ├── out_of_scope  → generate_decline       → END
              ├── feedback      → log_feedback           → END
              └── qa            → classify_category
                                      └── route()
                                            ├── clarify → generate_clarification → END
                                            └── rag     → search → generate_response → END

Memory: in-process dict keyed by chat_id, capped at last _MAX_HISTORY messages.
The graph is compiled once at module import (no external services required).
"""

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from habitantes.domain import tools
from habitantes.domain.nodes import (
    classify_intent,
    generate_clarification,
    generate_decline,
    generate_greeting,
    generate_response,
    log_feedback,
    route,
)
from habitantes.domain.state import AgentState

logger = logging.getLogger(__name__)

# ── Short-term memory (in-process, keyed by chat_id) ─────────────────────────

_MAX_HISTORY = 5
# MVP NOTE: in-memory session store. Not thread-safe. Acceptable for single-worker
# local use only. Replace with Redis or DB-backed store before multi-worker deployment.
# Thread-safety scope: tracked in T3.x (infrastructure layer).
#
# Structure: {chat_id: {"messages": [...], "category": "<EN name or empty>"}}
# category persists until the user picks a different number or sends a greeting.
_memory: dict[str, dict] = {}


def _get_history(chat_id: str) -> list[dict]:
    return list(_memory.get(chat_id, {}).get("messages", []))


def _get_selected_category(chat_id: str) -> str:
    return _memory.get(chat_id, {}).get("category", "")


def _update_memory(
    chat_id: str,
    user_message: str,
    assistant_answer: str,
    category: str,
    intent: str,
) -> None:
    existing = _memory.get(chat_id, {"messages": [], "category": ""})
    messages = existing["messages"] + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_answer},
    ]
    # Greeting resets the selected category; otherwise keep the newest non-empty value
    if intent == "greeting":
        new_category = ""
    else:
        new_category = category if category else existing["category"]
    _memory[chat_id] = {"messages": messages[-_MAX_HISTORY:], "category": new_category}


# ── Search node (wraps tools.hybrid_search) ───────────────────────────────────


def _search_node(state: AgentState) -> dict[str, Any]:
    """Call hybrid_search tool and write results into context_chunks."""
    category = state.get("category")
    result = tools.hybrid_search(
        query=state["message"],
        categories=[category] if category else None,
        top_k=5,
    )
    if "error" in result:
        logger.warning(
            "Search tool error: %s",
            result["error"]["error_code"],
            extra={"trace_id": state.get("trace_id")},
        )
        return {"context_chunks": [], "error": result["error"]}
    return {"context_chunks": result["chunks"]}


# ── Intent router (conditional edge) ─────────────────────────────────────────


def _route_intent(state: AgentState) -> str:
    """Route by intent; for 'qa' apply message-length routing directly."""
    intent = state.get("intent", "out_of_scope")
    if intent == "qa":
        return route(state)  # "rag" | "clarify"
    return intent


# ── Graph definition ──────────────────────────────────────────────────────────

_graph = StateGraph(AgentState)

_graph.add_node("classify_intent", classify_intent)
_graph.add_node("search", _search_node)
_graph.add_node("generate_response", generate_response)
_graph.add_node("generate_greeting", generate_greeting)
_graph.add_node("generate_decline", generate_decline)
_graph.add_node("generate_clarification", generate_clarification)
_graph.add_node("log_feedback", log_feedback)

_graph.set_entry_point("classify_intent")

_graph.add_conditional_edges(
    "classify_intent",
    _route_intent,
    {
        "greeting": "generate_greeting",
        "out_of_scope": "generate_decline",
        "feedback": "log_feedback",
        "rag": "search",
        "clarify": "generate_clarification",
    },
)

_graph.add_edge("search", "generate_response")
_graph.add_edge("generate_response", END)
_graph.add_edge("generate_greeting", END)
_graph.add_edge("generate_decline", END)
_graph.add_edge("generate_clarification", END)
_graph.add_edge("log_feedback", END)

_compiled_graph = _graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────


def run(
    chat_id: str,
    message: str,
    message_id: str,
    trace_id: str,
) -> dict[str, Any]:
    """Execute one agent turn end-to-end.

    Args:
        chat_id: Telegram chat identifier (used for memory lookup).
        message: User's raw message text.
        message_id: Unique message identifier.
        trace_id: Request trace ID propagated through all nodes.

    Returns:
        Final state dict with keys: answer, sources, intent, category,
        confidence, timings, error (None on success).
    """
    initial_state: AgentState = {
        "chat_id": chat_id,
        "message": message,
        "message_id": message_id,
        "trace_id": trace_id,
        "intent": "",
        "category": _get_selected_category(chat_id),  # persisted from last turn
        "context_chunks": [],
        "answer": "",
        "sources": [],
        "confidence": 0.0,
        "history": _get_history(chat_id),
        "timings": {},
        "error": None,
    }

    result = _compiled_graph.invoke(initial_state)
    _update_memory(
        chat_id,
        message,
        result.get("answer", ""),
        result.get("category", ""),
        result.get("intent", ""),
    )
    return result
