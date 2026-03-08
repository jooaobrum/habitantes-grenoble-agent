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

from habitantes.domain.prompts.intent import build_intent_messages
from habitantes.domain.prompts.synthesis import REACT_SYSTEM_PROMPT
from habitantes.domain.state import AgentState
from habitantes.domain.tools import get_search_tool

logger = logging.getLogger(__name__)

# ── Short-term memory (in-process, keyed by chat_id) ─────────────────────────


def _get_agent_settings():
    from habitantes.config import load_settings

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
        from habitantes.config import load_settings

        settings = load_settings()
        _llm = ChatOpenAI(
            model=settings.llm.model_name,
            api_key=settings.llm.openai_api_key,
            temperature=settings.agent.temperature,
            max_tokens=settings.api.max_tokens_per_response,
        )
    return _llm


# ── Greeting text (lazy) ─────────────────────────────────────────────────────

_greeting_text: str | None = None


def _get_greeting_text() -> str:
    global _greeting_text
    if _greeting_text is None:
        from habitantes.config import load_settings
        from habitantes.domain.categories import build_greeting_text

        _greeting_text = build_greeting_text(load_settings().categories)
    return _greeting_text


# ── Layer 1: Intent Classification ───────────────────────────────────────────


def _classify_intent(state: AgentState) -> dict:
    """Classify message intent. Short-circuits for category numbers."""
    t0 = time.monotonic()

    from habitantes.domain.categories import _get_categories, resolve_number

    cat = resolve_number(state["message"], _get_categories())
    if cat:
        return {
            "intent": "qa",
            "category": cat.en_name,
            "timings": {
                **(state.get("timings") or {}),
                "intent_ms": (time.monotonic() - t0) * 1000,
            },
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
                from habitantes.domain.categories import _get_categories, get_by_en_name

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
    tool_map = {search_tool.name: search_tool}

    # Only bind tools for qa intent (other intents don't need search)
    needs_tools = intent == "qa" and len(state.get("message", "").strip()) >= 10
    if needs_tools:
        llm_with_tools = llm.bind_tools([search_tool])
    else:
        llm_with_tools = llm

    msgs = _build_react_messages(state)
    context_chunks: list[dict] = []

    # ReAct loop
    for _ in range(_get_agent_settings().max_react_iterations):
        response = llm_with_tools.invoke(msgs)
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

                # Track chunks for eval (parse from tool result if possible)
                _track_chunks(tool_args.get("query", ""), state, context_chunks)

                msgs.append(
                    ToolMessage(
                        content=str(tool_result),
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

    # Extract final answer from the last LLM response
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

    top_score = max((c.get("score", 0.0) for c in context_chunks), default=0.0)
    confidence = _compute_confidence(intent, context_chunks, top_score)

    elapsed_ms = (time.monotonic() - t0) * 1000
    timings = {**(state.get("timings") or {}), "react_ms": elapsed_ms}

    return {
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
        "context_chunks": context_chunks,
        "timings": timings,
        "error": None,
    }


def _track_chunks(query: str, state: AgentState, context_chunks: list[dict]) -> None:
    """Track retrieved chunks for eval metrics by re-calling hybrid_search."""
    from habitantes.domain.tools import hybrid_search

    category = state.get("category", "")
    result = hybrid_search(
        query=query or state["message"],
        categories=[category] if category else None,
        top_k=5,
    )
    if "chunks" in result:
        context_chunks.clear()
        context_chunks.extend(result["chunks"])


def _compute_confidence(intent: str, chunks: list, top_score: float) -> float:
    """Compute confidence based on intent and retrieval results."""
    if intent in ("greeting", "out_of_scope", "feedback"):
        return 1.0
    if intent == "qa" and not chunks:
        return 0.5  # clarification or no results
    return min(1.0, float(top_score)) if top_score > 0 else 0.0


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
        "timings": {},
        "error": None,
    }

    # Layer 1: Intent classification
    classification = _classify_intent(initial_state)
    initial_state.update(classification)

    # Layer 2: ReAct agent
    result = _run_react_loop(initial_state)
    initial_state.update(result)

    _update_memory(
        chat_id,
        message,
        initial_state.get("answer", ""),
        initial_state.get("category", ""),
        initial_state.get("intent", ""),
    )
    return initial_state
