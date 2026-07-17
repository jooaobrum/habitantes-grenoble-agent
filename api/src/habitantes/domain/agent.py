"""Agent — Two-layer ReAct architecture with tool calling.

Architecture:

    Layer 1: classify_intent (deterministic + LLM classification)
        - Number shortcut: "1"-"19" → set category, skip LLM
        - LLM classifies: greeting | qa | feedback | out_of_scope

    Layer 2: ReAct agent (LLM + tool calling loop)
        - Receives the classified intent as context
        - For greeting / out_of_scope / feedback / clarify → responds directly
        - For rag → calls search_knowledge_base tool → synthesizes answer
        - Loops until the LLM decides no more tool calls are needed

    START → classify_intent → react_agent ⇄ tools → END

Memory: in-process dict keyed by chat_id, capped at last _MAX_HISTORY messages.
"""

import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APITimeoutError, OpenAIError, RateLimitError

from habitantes.config import load_settings
from habitantes.domain.cache import get_cache
from habitantes.domain.categories import (
    _get_categories,
    build_greeting_text,
    get_by_en_name,
    resolve_number,
)
from habitantes.domain.prompts.intent import build_intent_messages
from habitantes.domain.prompts.synthesis import (
    _NO_RESULTS_FALLBACK,
    REACT_SYSTEM_PROMPT,
)
from habitantes.domain.state import AgentState
from habitantes.domain.tools import (
    get_get_category_chunks_tool,
    get_list_subcategories_tool,
    get_search_tool,
)

logger = logging.getLogger(__name__)

# ── Short-term memory (in-process, keyed by chat_id) ─────────────────────────


def _get_agent_settings():
    return load_settings().agent


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
    if intent == "greeting":
        new_category = ""
    else:
        new_category = category if category else existing["category"]
    _memory[chat_id] = {
        "messages": messages[-_get_agent_settings().max_history :],
        "category": new_category,
    }


# ── LLM factory (lazy) ───────────────────────────────────────────────────────

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        settings = load_settings()
        _llm = ChatOpenAI(
            model=settings.llm.model_name,
            api_key=settings.llm.openai_api_key,
            temperature=settings.agent.temperature,
            max_tokens=settings.api.max_tokens_per_response,
            request_timeout=settings.api.openai_timeout_seconds,
        )
    return _llm


# ── Greeting text (lazy) ─────────────────────────────────────────────────────

_greeting_text: str | None = None


def _get_greeting_text() -> str:
    global _greeting_text
    if _greeting_text is None:
        _greeting_text = build_greeting_text(load_settings().categories)
    return _greeting_text


# ── Cost tracking ────────────────────────────────────────────────────────────


def _extract_usage(response: Any) -> tuple[int, int]:
    """Read (input_tokens, output_tokens) off an LLM response.

    Cost tracking is best-effort: a response without usage_metadata (SDK quirk)
    or with non-numeric values yields (0, 0) rather than raising — a missing
    token count must never be why a turn fails.
    """
    usage = getattr(response, "usage_metadata", None)
    if not isinstance(usage, dict):
        return 0, 0
    try:
        return int(usage.get("input_tokens", 0) or 0), int(
            usage.get("output_tokens", 0) or 0
        )
    except (TypeError, ValueError):
        return 0, 0


def _compute_cost(tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost from token counts and settings.pricing."""
    pricing = load_settings().pricing
    return (
        tokens_in * pricing.input_per_1m_usd / 1_000_000
        + tokens_out * pricing.output_per_1m_usd / 1_000_000
    )


# ── Error taxonomy (spec.md §6) ──────────────────────────────────────────────

_QDRANT_DOWN_MSG = (
    "Serviço temporariamente indisponível. Tente novamente em alguns minutos."
)
_OPENAI_DOWN_MSG = "Não consegui processar sua pergunta. Tente novamente."
_OPENAI_RATE_LIMIT_MSG = (
    "O sistema está muito ocupado agora. Tente novamente em 1 minuto."
)


def _map_openai_error(exc: Exception) -> dict:
    """Map an OpenAI SDK exception to the structured {error_code, message, retryable}."""
    if isinstance(exc, RateLimitError):
        return {
            "error_code": "OPENAI_RATE_LIMIT",
            "message": _OPENAI_RATE_LIMIT_MSG,
            "retryable": True,
        }
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return {
            "error_code": "OPENAI_UNREACHABLE",
            "message": _OPENAI_DOWN_MSG,
            "retryable": True,
        }
    return {
        "error_code": "OPENAI_ERROR",
        "message": _OPENAI_DOWN_MSG,
        "retryable": False,
    }


def _map_search_error(tool_error: dict) -> dict:
    """Map a search-tool {"error": {...}} contract to the user-facing PT message."""
    return {
        "error_code": tool_error.get("error_code", "SEARCH_ERROR"),
        "message": _QDRANT_DOWN_MSG,
        "retryable": tool_error.get("retryable", True),
    }


def _error_result(state: AgentState, error: dict) -> dict:
    """Build the run()-level error result: state fields + structured log."""
    logger.error(
        "Agent failure: %s",
        error["error_code"],
        extra={"trace_id": state.get("trace_id"), "error_code": error["error_code"]},
    )
    return {
        "answer": error["message"],
        "sources": [],
        "confidence": 0.0,
        "context_chunks": [],
        "error": error,
    }


def _finalize_with_error(
    state: AgentState, chat_id: str, message: str, exc: Exception
) -> AgentState:
    """Apply an OpenAI failure to state, persist memory, and return the turn result."""
    state.update(_error_result(state, _map_openai_error(exc)))
    state["cost_usd"] = _compute_cost(
        state.get("tokens_in", 0), state.get("tokens_out", 0)
    )
    # Use .get() so the error path never crashes if the failure happens before
    # intent/category are populated (e.g. auth error on the first OpenAI call).
    _update_memory(
        chat_id,
        message,
        state["answer"],
        state.get("category", ""),
        state.get("intent", ""),
    )
    return state


# ── Layer 1: Intent Classification ───────────────────────────────────────────


def _classify_intent(state: AgentState) -> dict:
    """Classify message intent. Short-circuits for category numbers."""
    t0 = time.monotonic()

    cat = resolve_number(state["message"], _get_categories())
    if cat:
        return {
            "intent": "qa",
            "category": cat.en_name,
            "tokens_in": 0,
            "tokens_out": 0,
            "timings": {
                **(state.get("timings") or {}),
                "intent_ms": (time.monotonic() - t0) * 1000,
            },
        }

    llm = _get_llm()
    messages = build_intent_messages(state["message"], history=state.get("history"))
    response = llm.invoke(messages)
    tokens_in, tokens_out = _extract_usage(response)

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
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "timings": {
            **(state.get("timings") or {}),
            "intent_ms": (time.monotonic() - t0) * 1000,
        },
    }


# ── Layer 2: ReAct Agent ─────────────────────────────────────────────────────

# Replaced by _get_agent_settings().max_react_iterations


def _build_react_messages(state: AgentState) -> list:
    """Build the message list for the ReAct agent."""
    intent = state.get("intent", "out_of_scope")
    category = state.get("category", "")
    message = state["message"]

    # Build system prompt with intent context
    system_content = REACT_SYSTEM_PROMPT

    # Add intent-specific instructions
    intent_context = f"\n\nINTENT CLASSIFICADO: {intent}"
    if category:
        intent_context += f"\nCATEGORIA SELECIONADA: {category}"

    if intent == "greeting":
        greeting_text = _get_greeting_text()
        intent_context += (
            f"\n\nO usuário está cumprimentando. Responda com esta mensagem "
            f"de boas-vindas EXATAMENTE como está:\n\n{greeting_text}"
        )
    elif intent == "out_of_scope":
        intent_context += (
            "\n\nO usuário fez uma pergunta fora do escopo. "
            "Recuse educadamente e diga que só pode ajudar com temas de expatriados em Grenoble."
        )
    elif intent == "feedback":
        intent_context += "\n\nO usuário está dando feedback. Agradeça pelo feedback."
    elif intent == "qa":
        if len(message.strip()) < 10:
            # Clarification case
            if category:
                entry = get_by_en_name(category, _get_categories())
                pt_name = entry.pt_name if entry else category
                intent_context += (
                    f"\n\nO usuário selecionou a categoria *{pt_name}* mas a pergunta "
                    f"é muito curta. Pergunte qual é a dúvida específica sobre este tema."
                )
            else:
                intent_context += (
                    "\n\nA pergunta é muito curta/ampla. Peça ao usuário para "
                    "dar mais detalhes sobre o que deseja saber."
                )
        else:
            intent_context += (
                "\n\nO usuário tem uma dúvida. Use a ferramenta search_knowledge_base "
                "para buscar informações relevantes na base de conhecimento e então "
                "sintetize uma resposta baseada nos resultados."
            )

    system_content += intent_context

    msgs: list = [SystemMessage(content=system_content)]

    # Add conversation history
    history = state.get("history") or []
    for turn in history:
        if turn["role"] == "user":
            msgs.append(HumanMessage(content=turn["content"]))
        elif turn["role"] == "assistant":
            msgs.append(AIMessage(content=turn["content"]))

    msgs.append(HumanMessage(content=message))
    return msgs


def _run_react_loop(state: AgentState) -> dict:
    """Execute the ReAct loop: LLM → tool calls → LLM → ... → final answer."""
    t0 = time.monotonic()
    intent = state.get("intent", "out_of_scope")

    llm = _get_llm()
    search_tool = get_search_tool()
    list_subs_tool = get_list_subcategories_tool()
    get_cat_chunks_tool = get_get_category_chunks_tool()

    tool_map = {
        search_tool.name: search_tool,
        list_subs_tool.name: list_subs_tool,
        get_cat_chunks_tool.name: get_cat_chunks_tool,
    }

    # Only bind tools for qa intent (other intents don't need search)
    needs_tools = intent == "qa" and len(state.get("message", "").strip()) >= 10
    if needs_tools:
        llm_with_tools = llm.bind_tools(
            [search_tool, list_subs_tool, get_cat_chunks_tool]
        )
    else:
        llm_with_tools = llm

    min_relevance = load_settings().search.min_relevance

    msgs = _build_react_messages(state)
    context_chunks: list[dict] = []
    gated = False
    gated_top_dense = 0.0
    search_error: dict | None = None
    tokens_in = 0
    tokens_out = 0

    # ReAct loop
    for _ in range(_get_agent_settings().max_react_iterations):
        response = llm_with_tools.invoke(msgs)
        ti, to = _extract_usage(response)
        tokens_in += ti
        tokens_out += to
        msgs.append(response)

        # If no tool calls, we have the final answer
        if not getattr(response, "tool_calls", None):
            break

        # Process tool calls
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            if tool_name in tool_map:
                # Inject category from state if not provided
                if "category" not in tool_args or not tool_args["category"]:
                    category = state.get("category", "")
                    if category:
                        tool_args["category"] = category

                tool_result = tool_map[tool_name].invoke(tool_args)

                # If the tool surfaced a structured {"error": {...}}, short-circuit
                # with the spec's PT failure message — no further LLM calls.
                if isinstance(tool_result, dict) and "error" in tool_result:
                    search_error = _map_search_error(tool_result["error"])
                    logger.error(
                        "Search tool failure: %s",
                        tool_result["error"].get("message"),
                        extra={
                            "trace_id": state.get("trace_id"),
                            "error_code": search_error["error_code"],
                        },
                    )
                    context_chunks.clear()
                    break

                # If tool_result is a dict with "chunks" (from search_knowledge_base),
                # apply the relevance gate before letting the LLM synthesize.
                if isinstance(tool_result, dict) and "chunks" in tool_result:
                    raw_chunks = tool_result["chunks"]
                    relevant = [
                        c
                        for c in raw_chunks
                        if float(c.get("dense_score", 0.0)) >= min_relevance
                    ]
                    if not relevant and not context_chunks:
                        # Nothing clears the floor on any search this turn →
                        # off-topic / no reliable match. Short-circuit with the
                        # fallback, no synthesis LLM call.
                        gated = True
                        gated_top_dense = max(
                            (float(c.get("dense_score", 0.0)) for c in raw_chunks),
                            default=0.0,
                        )
                        break
                    elif not relevant:
                        # This particular search came up empty, but an earlier
                        # search this turn already found relevant context —
                        # let the LLM decide whether to retry or synthesize.
                        tool_content = (
                            "Nenhum resultado relevante encontrado para esta busca."
                        )
                    else:
                        # Accumulate across every search_knowledge_base call this
                        # turn (dedup by thread_id) so context_chunks reflects
                        # everything the LLM actually saw, not just the last call.
                        seen_ids = {c.get("thread_id") for c in context_chunks}
                        for c in relevant:
                            if c.get("thread_id") not in seen_ids:
                                context_chunks.append(c)
                                seen_ids.add(c.get("thread_id"))
                        tool_content = _format_relevant_chunks(relevant)
                else:
                    tool_content = str(tool_result)

                msgs.append(
                    ToolMessage(
                        content=tool_content,
                        tool_call_id=tool_call["id"],
                    )
                )
            else:
                msgs.append(
                    ToolMessage(
                        content=f"Tool '{tool_name}' not found.",
                        tool_call_id=tool_call["id"],
                    )
                )

        if gated or search_error:
            break

    # Extract final answer from the last LLM response
    if search_error:
        answer = search_error["message"]
    elif gated:
        answer = _NO_RESULTS_FALLBACK
    else:
        answer = ""
        if msgs:
            last = msgs[-1]
            content = getattr(last, "content", None)
            if content:
                answer = str(content)

    # Build sources from context_chunks
    sources = [
        {
            "text_snippet": (chunk.get("text") or chunk.get("answer", ""))[:200],
            "date": chunk.get("date", ""),
            "category": chunk.get("category", ""),
        }
        for chunk in context_chunks
    ]

    top_dense = max(
        (float(c.get("dense_score", 0.0)) for c in context_chunks),
        default=gated_top_dense,
    )
    confidence = (
        0.0
        if search_error
        else _compute_confidence(intent, context_chunks, top_dense, gated)
    )

    elapsed_ms = (time.monotonic() - t0) * 1000
    timings = {**(state.get("timings") or {}), "react_ms": elapsed_ms}

    return {
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
        "context_chunks": context_chunks,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "timings": timings,
        "error": search_error,
    }


def _format_relevant_chunks(chunks: list[dict]) -> str:
    """Format gate-passing chunks into the ReAct tool-message context block."""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        cat = chunk.get("category", "geral")
        date = chunk.get("date", "data desconhecida")
        text = chunk.get("text") or chunk.get("answer", "")
        parts.append(f"[{i}] Categoria: {cat} | Data: {date}\n{text}")
    return "\n\n".join(parts)


def _compute_confidence(
    intent: str, chunks: list, top_dense: float, gated: bool = False
) -> float:
    """Compute confidence from intent and the top dense cosine similarity."""
    if intent in ("greeting", "out_of_scope", "feedback"):
        return 1.0
    if gated:
        return float(top_dense)  # below the relevance floor → intentionally low
    if intent == "qa" and not chunks:
        return 0.5  # clarification (short query, no search performed)
    return min(1.0, float(top_dense)) if top_dense > 0 else 0.0


# ── Public entry point ────────────────────────────────────────────────────────


def run(
    chat_id: str,
    message: str,
    message_id: str,
    trace_id: str,
) -> dict[str, Any]:
    """Execute one agent turn end-to-end.

    Two-layer architecture:
      1. classify_intent — determines intent (greeting/qa/feedback/out_of_scope)
      2. react_agent — ReAct loop with tool calling for search

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
        "category": _get_selected_category(chat_id),
        "context_chunks": [],
        "answer": "",
        "sources": [],
        "confidence": 0.0,
        "history": _get_history(chat_id),
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "timings": {},
        "cached": False,
        "error": None,
    }

    # Layer 1: Intent classification
    try:
        classification = _classify_intent(initial_state)
    except OpenAIError as exc:
        return _finalize_with_error(initial_state, chat_id, message, exc)
    initial_state.update(classification)

    # Cache check (only for QA intent with sufficient length)
    cache = get_cache()
    if cache and initial_state["intent"] == "qa" and len(message.strip()) >= 10:
        cached_result = cache.get(message, initial_state["category"])
        if cached_result:
            initial_state.update(cached_result)
            initial_state["cached"] = True
            # Only the classification LLM call ran this turn (cache short-circuits
            # the ReAct loop), so tokens come solely from _classify_intent.
            initial_state["cost_usd"] = _compute_cost(
                initial_state["tokens_in"], initial_state["tokens_out"]
            )
            _update_memory(
                chat_id,
                message,
                initial_state["answer"],
                initial_state["category"],
                initial_state["intent"],
            )
            return initial_state

    # Layer 2: ReAct agent
    try:
        result = _run_react_loop(initial_state)
    except OpenAIError as exc:
        return _finalize_with_error(initial_state, chat_id, message, exc)
    # Sum classification + ReAct usage before .update() overwrites the phase-1
    # counts with the ReAct-loop-only counts.
    total_in = classification.get("tokens_in", 0) + result.get("tokens_in", 0)
    total_out = classification.get("tokens_out", 0) + result.get("tokens_out", 0)
    initial_state.update(result)
    initial_state["tokens_in"] = total_in
    initial_state["tokens_out"] = total_out
    initial_state["cost_usd"] = _compute_cost(total_in, total_out)

    # Store in cache if successful
    if (
        cache
        and initial_state["intent"] == "qa"
        and initial_state.get("answer")
        and not initial_state.get("error")
    ):
        cache.set(
            message,
            initial_state["category"],
            {
                "answer": initial_state["answer"],
                "sources": initial_state["sources"],
                "confidence": initial_state["confidence"],
                "context_chunks": initial_state["context_chunks"],
            },
        )

    _update_memory(
        chat_id,
        message,
        initial_state["answer"],
        initial_state["category"],
        initial_state["intent"],
    )
    return initial_state
