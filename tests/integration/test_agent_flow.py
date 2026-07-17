"""Integration tests for domain/agent.py (ReAct architecture).

The two-layer ReAct agent is exercised end-to-end. All external calls
(LLM + Qdrant) are mocked via monkeypatch so no real services are needed.
"""

from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIConnectionError, AuthenticationError, RateLimitError

import habitantes.domain.agent as agent_module
import habitantes.domain.categories as categories_module
import habitantes.domain.tools.search as tools_module
from habitantes.config import CategoryEntry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ai_response(content: str, tool_calls=None) -> MagicMock:
    """Create a mock AIMessage-like response."""
    resp = MagicMock()
    resp.content = content
    resp.tool_calls = tool_calls or []
    return resp


def _make_llm(*responses) -> MagicMock:
    """LLM mock whose .invoke() returns successive responses (Layer 2: ReAct loop).

    Each response can be a string (converted to AIMessage mock) or a
    pre-built mock (for tool call responses). Layer 1 (intent classification)
    goes through `_get_intent_llm()` instead — see `_make_intent_llm`.
    """
    llm = MagicMock()
    mocks = []
    for r in responses:
        if isinstance(r, str):
            mocks.append(_ai_response(r))
        else:
            mocks.append(r)
    llm.invoke.side_effect = mocks

    # bind_tools should return the same LLM (tools are handled in the loop)
    llm.bind_tools = MagicMock(return_value=llm)
    return llm


def _make_intent_llm(intent: str) -> MagicMock:
    """Mock for `_get_intent_llm()`: one `.invoke()` call returning a forced
    IntentClassification tool call, like `bind_tools(..., tool_choice=...)`
    produces.
    """
    response = _ai_response(
        "",
        tool_calls=[
            {
                "name": "IntentClassification",
                "args": {"intent": intent},
                "id": "call_intent",
            }
        ],
    )
    response.usage_metadata = {"input_tokens": 10, "output_tokens": 2}
    intent_llm = MagicMock()
    intent_llm.invoke.return_value = response
    return intent_llm


def _make_raising_intent_llm(exc: Exception) -> MagicMock:
    """Mock for `_get_intent_llm()` whose `.invoke()` raises `exc`."""
    intent_llm = MagicMock()
    intent_llm.invoke.side_effect = exc
    return intent_llm


def _run(message: str, chat_id: str = "chat-test", **kwargs) -> dict:
    return agent_module.run(
        chat_id=chat_id,
        message=message,
        message_id="msg-1",
        trace_id="trace-1",
        **kwargs,
    )


_FAKE_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _rate_limit_error() -> RateLimitError:
    resp = httpx.Response(
        429, request=_FAKE_REQUEST, json={"error": {"message": "rate limited"}}
    )
    return RateLimitError("rate limited", response=resp, body=None)


def _auth_error() -> AuthenticationError:
    resp = httpx.Response(
        401, request=_FAKE_REQUEST, json={"error": {"message": "invalid api key"}}
    )
    return AuthenticationError("invalid api key", response=resp, body=None)


def _connection_error() -> APIConnectionError:
    return APIConnectionError(request=_FAKE_REQUEST)


def _make_raising_llm(exc: Exception, *ok_responses) -> MagicMock:
    """LLM mock whose .invoke() raises `exc` after any successful `ok_responses`."""
    llm = MagicMock()
    mocks = [_ai_response(r) if isinstance(r, str) else r for r in ok_responses]
    llm.invoke.side_effect = [*mocks, exc]
    llm.bind_tools = MagicMock(return_value=llm)
    return llm


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_singletons():
    """Reset in-process memory and LLM singletons before every test."""
    agent_module._memory.clear()
    agent_module._llm = None
    agent_module._intent_llm = None
    yield
    agent_module._memory.clear()
    agent_module._llm = None
    agent_module._intent_llm = None


# ── Greeting flow ─────────────────────────────────────────────────────────────


def test_greeting_flow(monkeypatch):
    # Intent classification returns greeting, then ReAct responds with greeting
    monkeypatch.setattr(
        agent_module, "_get_intent_llm", lambda: _make_intent_llm("greeting")
    )
    shared_llm = _make_llm(
        "Olá! Sou o assistente dos brasileiros em Grenoble.",  # Layer 2: ReAct response
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Olá, tudo bem?")

    assert result["intent"] == "greeting"
    assert len(result["answer"]) > 0
    assert result["confidence"] == 1.0


def test_intent_classification_falls_back_when_structured_output_fails(monkeypatch):
    """If the model doesn't return the forced IntentClassification tool call
    (or returns args that don't validate), classify_intent must fall back to
    out_of_scope instead of raising."""
    no_tool_call_response = _ai_response("", tool_calls=[])
    no_tool_call_response.usage_metadata = {"input_tokens": 10, "output_tokens": 2}
    intent_llm = MagicMock()
    intent_llm.invoke.return_value = no_tool_call_response
    monkeypatch.setattr(agent_module, "_get_intent_llm", lambda: intent_llm)
    shared_llm = _make_llm(
        "Desculpe, só consigo ajudar com temas de expatriados em Grenoble.",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Olá, tudo bem?")

    assert result["intent"] == "out_of_scope"


# ── Out-of-scope flow ─────────────────────────────────────────────────────────


def test_out_of_scope_flow(monkeypatch):
    monkeypatch.setattr(
        agent_module, "_get_intent_llm", lambda: _make_intent_llm("out_of_scope")
    )
    shared_llm = _make_llm(
        "Desculpe, só consigo ajudar com temas de expatriados em Grenoble.",  # Layer 2
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Qual é a capital do Japão?")

    assert result["intent"] == "out_of_scope"
    assert result["confidence"] == 1.0
    assert len(result["answer"]) > 0


# ── Feedback flow ─────────────────────────────────────────────────────────────


def test_feedback_flow(monkeypatch):
    monkeypatch.setattr(
        agent_module, "_get_intent_llm", lambda: _make_intent_llm("feedback")
    )
    shared_llm = _make_llm(
        "Obrigado pelo seu feedback!",  # Layer 2
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("👍")

    assert result["intent"] == "feedback"
    assert len(result["answer"]) > 0


# ── Number selection → clarify with category context ─────────────────────────


def test_number_selection_sets_category_and_asks_for_question(monkeypatch):
    _fake_cats = [
        CategoryEntry(pt_name="Visto & Residência", en_name="Visa & Residency"),
        CategoryEntry(pt_name="Bancos & Finanças", en_name="Banking & Finance"),
    ]
    monkeypatch.setattr(categories_module, "_get_categories", lambda: _fake_cats)
    monkeypatch.setattr(categories_module, "_categories_cache", None)

    # For number shortcut, Layer 1 bypasses LLM entirely.
    # Layer 2 ReAct just responds with clarification (no tool call needed).
    shared_llm = _make_llm(
        "Ótimo! Você escolheu *Visto & Residência*. Qual é a sua dúvida?",  # Layer 2
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("1", chat_id="chat-num")

    assert result["intent"] == "qa"
    assert result["category"] == "Visa & Residency"
    assert len(result["answer"]) > 0


def test_category_persists_to_next_turn(monkeypatch):
    _fake_cats = [
        CategoryEntry(pt_name="Visto & Residência", en_name="Visa & Residency"),
    ]
    monkeypatch.setattr(categories_module, "_get_categories", lambda: _fake_cats)
    monkeypatch.setattr(categories_module, "_categories_cache", None)

    # Turn 1: user picks category 1 (number shortcut skips intent LLM)
    llm_turn1 = _make_llm(
        "Ótimo! Você escolheu *Visto & Residência*. Qual é a sua dúvida?",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: llm_turn1)
    _run("1", chat_id="chat-persist")

    # Turn 2: user asks a question — category should be pre-loaded from memory
    # ReAct: LLM calls tool, then responds
    tool_call_response = _ai_response(
        "",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"query": "Como renovar o titre de séjour?"},
                "id": "call_123",
            }
        ],
    )
    final_response = _ai_response("Resposta sobre visto.")

    monkeypatch.setattr(agent_module, "_get_intent_llm", lambda: _make_intent_llm("qa"))
    shared_llm = _make_llm(
        tool_call_response,  # Layer 2: LLM decides to search
        final_response,  # Layer 2: LLM synthesizes answer
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    # Mock the search tool
    mock_tool = MagicMock()
    mock_tool.name = "search_knowledge_base"
    mock_tool.invoke.return_value = "[1] Info sobre visto"
    monkeypatch.setattr(tools_module, "get_search_tool", lambda: mock_tool)
    monkeypatch.setattr(
        tools_module,
        "hybrid_search",
        lambda **_: {
            "chunks": [
                {
                    "text": "Info visto",
                    "question": "Q",
                    "answer": "Info visto",
                    "source": "ANEF",
                    "thread_id": 123,
                    "date": "2024-01-01",
                    "category": "Visa & Residency",
                    "score": 0.9,
                }
            ]
        },
    )

    result = _run("Como renovar o titre de séjour?", chat_id="chat-persist")

    assert result["category"] == "Visa & Residency"
    assert result["intent"] == "qa"


# ── QA → clarify flow (short message) ────────────────────────────────────────


def test_qa_clarify_flow(monkeypatch):
    monkeypatch.setattr(agent_module, "_get_intent_llm", lambda: _make_intent_llm("qa"))
    shared_llm = _make_llm(
        "Sua pergunta é muito ampla. Pode dar mais detalhes?",  # Layer 2
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("visto")

    assert result["intent"] == "qa"
    assert len(result["answer"]) > 0


# ── QA → RAG → happy-path (with tool calling) ────────────────────────────────


def test_qa_rag_happy_path(monkeypatch):
    tool_call_response = _ai_response(
        "",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"query": "Como renovar o titre de séjour em Grenoble?"},
                "id": "call_abc",
            }
        ],
    )
    final_response = _ai_response("Acesse o site da ANEF para renovar.")

    monkeypatch.setattr(agent_module, "_get_intent_llm", lambda: _make_intent_llm("qa"))
    shared_llm = _make_llm(
        tool_call_response,  # Layer 2: tool call
        final_response,  # Layer 2: final answer
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    mock_tool = MagicMock()
    mock_tool.name = "search_knowledge_base"
    mock_tool.invoke.return_value = "[1] Para renovar acesse a ANEF."
    monkeypatch.setattr(tools_module, "get_search_tool", lambda: mock_tool)
    monkeypatch.setattr(
        tools_module,
        "hybrid_search",
        lambda **_: {
            "chunks": [
                {
                    "text": "Para renovar acesse a ANEF.",
                    "question": "Como renovar?",
                    "answer": "Para renovar acesse a ANEF.",
                    "source": "Visa & Residency",
                    "thread_id": 456,
                    "date": "2024-05-01",
                    "category": "Visa & Residency",
                    "score": 0.92,
                    "dense_score": 0.92,
                }
            ]
        },
    )

    result = _run("Como renovar o titre de séjour em Grenoble?")

    assert result["intent"] == "qa"
    assert result["answer"] == "Acesse o site da ANEF para renovar."
    assert result["confidence"] > 0.0
    # No numbered-menu pick happened this turn, but retrieval matched
    # "Visa & Residency" chunks — that should fall through as the logged
    # category instead of staying blank (Control Center "top categories").
    assert result["category"] == "Visa & Residency"


def test_react_loop_nudges_and_retries_on_empty_response(monkeypatch):
    """Gemini occasionally exhausts its output budget on internal reasoning and
    returns neither content nor a tool call. The ReAct loop must nudge with a
    follow-up message and retry instead of surfacing a blank answer."""
    monkeypatch.setattr(agent_module, "_get_intent_llm", lambda: _make_intent_llm("qa"))
    empty_response = _ai_response("", tool_calls=[])
    final_response = _ai_response("Aqui está a resposta.")
    shared_llm = _make_llm(empty_response, final_response)
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Pergunta qualquer sobre Grenoble?")

    assert result["answer"] == "Aqui está a resposta."


# ── Category fallback for analytics (free-text, no menu pick) ───────────────


def test_free_text_query_derives_category_from_sources(monkeypatch):
    """`state['category']` is only set by the numbered-menu shortcut; free-text
    questions must still surface *some* category for usage aggregation, derived
    from whichever category the retrieved chunks belong to."""
    tool_call_response = _ai_response(
        "",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"query": "Como abrir conta bancária?"},
                "id": "call_bank",
            }
        ],
    )
    final_response = _ai_response("Veja como abrir conta em um banco francês.")

    monkeypatch.setattr(agent_module, "_get_intent_llm", lambda: _make_intent_llm("qa"))
    shared_llm = _make_llm(
        tool_call_response,
        final_response,
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    mock_tool = MagicMock()
    mock_tool.name = "search_knowledge_base"
    mock_tool.invoke.return_value = "[1] Abra uma conta no banco."
    monkeypatch.setattr(tools_module, "get_search_tool", lambda: mock_tool)
    monkeypatch.setattr(
        tools_module,
        "hybrid_search",
        lambda **_: {
            "chunks": [
                {
                    "text": "Abra uma conta no banco.",
                    "question": "Como abrir conta?",
                    "answer": "Abra uma conta no banco.",
                    "source": "Banking & Finance",
                    "thread_id": 789,
                    "date": "2024-02-01",
                    "category": "Banking & Finance",
                    "score": 0.88,
                    "dense_score": 0.88,
                }
            ]
        },
    )

    result = _run("Como abrir conta bancária?", chat_id="chat-no-category")

    assert result["category"] == "Banking & Finance"


# ── QA → RAG → search tool error ─────────────────────────────────────────────


def test_qa_rag_search_error_returns_answer(monkeypatch):
    tool_call_response = _ai_response(
        "",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"query": "Como abrir conta no banco?"},
                "id": "call_err",
            }
        ],
    )
    final_response = _ai_response("Não encontrei informação confiável sobre esse tema.")

    monkeypatch.setattr(agent_module, "_get_intent_llm", lambda: _make_intent_llm("qa"))
    shared_llm = _make_llm(
        tool_call_response,  # Layer 2: tool call
        final_response,  # Layer 2: fallback answer
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    mock_tool = MagicMock()
    mock_tool.name = "search_knowledge_base"
    mock_tool.invoke.return_value = "Erro na busca: Qdrant unreachable"
    monkeypatch.setattr(tools_module, "get_search_tool", lambda: mock_tool)
    monkeypatch.setattr(
        tools_module,
        "hybrid_search",
        lambda **_: {
            "error": {
                "error_code": "QDRANT_UNREACHABLE",
                "message": "down",
                "retryable": True,
            }
        },
    )

    result = _run("Como abrir conta no banco sendo estrangeiro?")

    assert result["intent"] == "qa"
    assert len(result["answer"]) > 0


# ── Error taxonomy (P2-01) ───────────────────────────────────────────────────


def test_openai_auth_failure_returns_pt_fallback(monkeypatch):
    """Killing the OpenAI key blows up on the intent-classification LLM call."""
    monkeypatch.setattr(
        agent_module, "_get_intent_llm", lambda: _make_raising_intent_llm(_auth_error())
    )

    result = _run("Como renovar o titre de séjour?")

    assert result["answer"] == "Não consegui processar sua pergunta. Tente novamente."
    assert result["error"] == {
        "error_code": "OPENAI_ERROR",
        "message": "Não consegui processar sua pergunta. Tente novamente.",
        "retryable": False,
    }
    assert result["confidence"] == 0.0


def test_openai_connection_error_during_react_loop(monkeypatch):
    """Intent classification succeeds; the ReAct-layer LLM call fails."""
    monkeypatch.setattr(
        agent_module, "_get_intent_llm", lambda: _make_intent_llm("greeting")
    )
    shared_llm = _make_raising_llm(_connection_error())
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Oi!")

    assert result["answer"] == "Não consegui processar sua pergunta. Tente novamente."
    assert result["error"]["error_code"] == "OPENAI_UNREACHABLE"
    assert result["error"]["retryable"] is True


def test_openai_rate_limit_returns_pt_message(monkeypatch):
    monkeypatch.setattr(
        agent_module, "_get_intent_llm", lambda: _make_intent_llm("greeting")
    )
    shared_llm = _make_raising_llm(_rate_limit_error())
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Oi!")

    assert (
        result["answer"]
        == "O sistema está muito ocupado agora. Tente novamente em 1 minuto."
    )
    assert result["error"]["error_code"] == "OPENAI_RATE_LIMIT"
    assert result["error"]["retryable"] is True


def test_qdrant_unreachable_short_circuits_with_pt_message(monkeypatch):
    """A structured search-tool error must short-circuit — no synthesis LLM call."""
    tool_call_response = _ai_response(
        "",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"query": "Como abrir conta no banco?"},
                "id": "call_err",
            }
        ],
    )
    monkeypatch.setattr(agent_module, "_get_intent_llm", lambda: _make_intent_llm("qa"))
    # Only 1 Layer-2 response queued: the tool-call decision. If the
    # orchestrator wrongly asked the LLM to synthesize a 2nd time, this mock
    # would raise StopIteration.
    shared_llm = _make_llm(tool_call_response)
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    # search_knowledge_base is a real LangChain tool wrapper around hybrid_search;
    # mock hybrid_search itself (bare-name lookup inside search.py picks this up).
    monkeypatch.setattr(
        tools_module,
        "hybrid_search",
        lambda **_: {
            "error": {
                "error_code": "QDRANT_UNREACHABLE",
                "message": "connection refused",
                "retryable": True,
            }
        },
    )

    result = _run("Como abrir conta no banco sendo estrangeiro?")

    assert result["intent"] == "qa"
    assert (
        result["answer"]
        == "Serviço temporariamente indisponível. Tente novamente em alguns minutos."
    )
    assert result["error"]["error_code"] == "QDRANT_UNREACHABLE"
    assert result["confidence"] == 0.0


# ── Memory tests ──────────────────────────────────────────────────────────────


def test_memory_populated_after_run(monkeypatch):
    monkeypatch.setattr(
        agent_module, "_get_intent_llm", lambda: _make_intent_llm("greeting")
    )
    shared_llm = _make_llm("Olá!")
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    _run("Oi!", chat_id="chat-mem")

    history = agent_module._get_history("chat-mem")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Oi!"
    assert history[1]["role"] == "assistant"


def test_memory_capped_at_max_history(monkeypatch):
    for i in range(5):
        monkeypatch.setattr(
            agent_module, "_get_intent_llm", lambda: _make_intent_llm("greeting")
        )
        shared_llm = _make_llm(f"Resposta {i}")
        monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)
        agent_module._llm = None
        agent_module._intent_llm = None
        _run(f"Mensagem {i}", chat_id="chat-cap")

    history = agent_module._get_history("chat-cap")
    assert len(history) <= agent_module._get_agent_settings().max_history


def test_history_passed_into_initial_state(monkeypatch):
    agent_module._memory["chat-hist"] = {
        "messages": [
            {"role": "user", "content": "Oi"},
            {"role": "assistant", "content": "Olá!"},
        ],
        "category": "",
    }
    monkeypatch.setattr(
        agent_module, "_get_intent_llm", lambda: _make_intent_llm("greeting")
    )
    shared_llm = _make_llm("Olá de novo!")
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Oi de novo!", chat_id="chat-hist")
    assert result["answer"]
