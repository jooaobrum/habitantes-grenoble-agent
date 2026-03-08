"""Integration tests for domain/agent.py (ReAct architecture).

The two-layer ReAct agent is exercised end-to-end. All external calls
(LLM + Qdrant) are mocked via monkeypatch so no real services are needed.
"""

from unittest.mock import MagicMock

import pytest

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
    """LLM mock whose .invoke() returns successive responses.

    Each response can be a string (converted to AIMessage mock) or a
    pre-built mock (for tool call responses).
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


def _run(message: str, chat_id: str = "chat-test", **kwargs) -> dict:
    return agent_module.run(
        chat_id=chat_id,
        message=message,
        message_id="msg-1",
        trace_id="trace-1",
        **kwargs,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_singletons():
    """Reset in-process memory and LLM singletons before every test."""
    agent_module._memory.clear()
    agent_module._llm = None
    yield
    agent_module._memory.clear()
    agent_module._llm = None


# ── Greeting flow ─────────────────────────────────────────────────────────────


def test_greeting_flow(monkeypatch):
    # Intent classification returns greeting, then ReAct responds with greeting
    shared_llm = _make_llm(
        '{"intent": "greeting"}',  # Layer 1: classify_intent
        "Olá! Sou o assistente dos brasileiros em Grenoble.",  # Layer 2: ReAct response
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Olá, tudo bem?")

    assert result["intent"] == "greeting"
    assert len(result["answer"]) > 0
    assert result["confidence"] == 1.0


# ── Out-of-scope flow ─────────────────────────────────────────────────────────


def test_out_of_scope_flow(monkeypatch):
    shared_llm = _make_llm(
        '{"intent": "out_of_scope"}',  # Layer 1
        "Desculpe, só consigo ajudar com temas de expatriados em Grenoble.",  # Layer 2
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Qual é a capital do Japão?")

    assert result["intent"] == "out_of_scope"
    assert result["confidence"] == 1.0
    assert len(result["answer"]) > 0


# ── Feedback flow ─────────────────────────────────────────────────────────────


def test_feedback_flow(monkeypatch):
    shared_llm = _make_llm(
        '{"intent": "feedback"}',  # Layer 1
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

    shared_llm = _make_llm(
        '{"intent": "qa"}',  # Layer 1
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
    shared_llm = _make_llm(
        '{"intent": "qa"}',  # Layer 1
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

    shared_llm = _make_llm(
        '{"intent": "qa"}',  # Layer 1
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
                }
            ]
        },
    )

    result = _run("Como renovar o titre de séjour em Grenoble?")

    assert result["intent"] == "qa"
    assert result["answer"] == "Acesse o site da ANEF para renovar."
    assert result["confidence"] > 0.0


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

    shared_llm = _make_llm(
        '{"intent": "qa"}',  # Layer 1
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


# ── Memory tests ──────────────────────────────────────────────────────────────


def test_memory_populated_after_run(monkeypatch):
    shared_llm = _make_llm(
        '{"intent": "greeting"}',
        "Olá!",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    _run("Oi!", chat_id="chat-mem")

    history = agent_module._get_history("chat-mem")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Oi!"
    assert history[1]["role"] == "assistant"


def test_memory_capped_at_max_history(monkeypatch):
    for i in range(5):
        shared_llm = _make_llm(
            '{"intent": "greeting"}',
            f"Resposta {i}",
        )
        monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)
        agent_module._llm = None
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
    shared_llm = _make_llm(
        '{"intent": "greeting"}',
        "Olá de novo!",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Oi de novo!", chat_id="chat-hist")
    assert result["answer"]
