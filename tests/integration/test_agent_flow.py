"""Integration tests for domain/agent.py.

The full LangGraph graph is exercised end-to-end. All external calls
(LLM + Qdrant) are mocked via monkeypatch so no real services are needed.
"""

from unittest.mock import MagicMock

import pytest

import habitantes.domain.agent as agent_module
import habitantes.domain.categories as categories_module
import habitantes.domain.nodes as nodes_module
import habitantes.domain.tools as tools_module
from habitantes.config import CategoryEntry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    return resp


def _make_llm(*responses: str) -> MagicMock:
    """LLM mock whose .invoke() returns successive responses."""
    llm = MagicMock()
    llm.invoke.side_effect = [_llm_response(r) for r in responses]
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
def clear_memory():
    """Reset in-process memory before every test."""
    agent_module._memory.clear()
    yield
    agent_module._memory.clear()


# ── Compile check ─────────────────────────────────────────────────────────────


def test_graph_compiles():
    assert agent_module._compiled_graph is not None


# ── Greeting flow ─────────────────────────────────────────────────────────────


def test_greeting_flow(monkeypatch):
    monkeypatch.setattr(
        nodes_module, "_get_llm", lambda: _make_llm('{"intent": "greeting"}')
    )
    monkeypatch.setattr(nodes_module, "_llm", None)

    result = _run("Olá, tudo bem?")

    assert result["intent"] == "greeting"
    assert "Olá" in result["answer"]
    assert result["confidence"] == 1.0


# ── Out-of-scope flow ─────────────────────────────────────────────────────────


def test_out_of_scope_flow(monkeypatch):
    monkeypatch.setattr(
        nodes_module, "_get_llm", lambda: _make_llm('{"intent": "out_of_scope"}')
    )
    monkeypatch.setattr(nodes_module, "_llm", None)

    result = _run("Qual é a capital do Japão?")

    assert result["intent"] == "out_of_scope"
    assert result["confidence"] == 1.0
    assert len(result["answer"]) > 0


# ── Feedback flow ─────────────────────────────────────────────────────────────


def test_feedback_flow(monkeypatch):
    monkeypatch.setattr(
        nodes_module, "_get_llm", lambda: _make_llm('{"intent": "feedback"}')
    )
    monkeypatch.setattr(nodes_module, "_llm", None)

    result = _run("👍")

    assert result["intent"] == "feedback"
    assert (
        "feedback" in result["answer"].lower() or "obrigado" in result["answer"].lower()
    )


# ── Number selection → clarify with category context ─────────────────────────


def test_number_selection_sets_category_and_asks_for_question(monkeypatch):
    _fake_cats = [
        CategoryEntry(pt_name="Visto & Residência", en_name="Visa & Residency"),
        CategoryEntry(pt_name="Bancos & Finanças", en_name="Banking & Finance"),
    ]
    monkeypatch.setattr(categories_module, "_get_categories", lambda: _fake_cats)
    monkeypatch.setattr(categories_module, "_categories_cache", None)

    result = _run("1", chat_id="chat-num")

    assert result["intent"] == "qa"
    assert result["category"] == "Visa & Residency"
    # clarification response should name the Portuguese category
    assert "Visto & Residência" in result["answer"]


def test_category_persists_to_next_turn(monkeypatch):
    _fake_cats = [
        CategoryEntry(pt_name="Visto & Residência", en_name="Visa & Residency"),
    ]
    monkeypatch.setattr(categories_module, "_get_categories", lambda: _fake_cats)
    monkeypatch.setattr(categories_module, "_categories_cache", None)

    # Turn 1: user picks category 1
    _run("1", chat_id="chat-persist")

    # Turn 2: user asks a question — category should be pre-loaded from memory
    shared_llm = _make_llm('{"intent": "qa"}', "Resposta sobre visto.")
    monkeypatch.setattr(nodes_module, "_get_llm", lambda: shared_llm)
    monkeypatch.setattr(nodes_module, "_llm", None)
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
                    "date": "2024-01-01",
                    "category": "Visa & Residency",
                    "score": 0.9,
                }
            ]
        },
    )
    monkeypatch.setattr(tools_module, "_get_collection_name", lambda: "test")

    result = _run("Como renovar o titre de séjour?", chat_id="chat-persist")

    assert result["category"] == "Visa & Residency"
    assert result["intent"] == "qa"


# ── QA → clarify flow (short message) ────────────────────────────────────────


def test_qa_clarify_flow(monkeypatch):
    monkeypatch.setattr(nodes_module, "_get_llm", lambda: _make_llm('{"intent": "qa"}'))
    monkeypatch.setattr(nodes_module, "_llm", None)

    # Short message → route() returns "clarify"
    result = _run("visto")

    assert result["intent"] == "qa"
    assert result["confidence"] == 0.5
    assert len(result["answer"]) > 0


# ── QA → RAG → happy-path ─────────────────────────────────────────────────────


def test_qa_rag_happy_path(monkeypatch):
    # One shared instance so side_effect advances across all node calls
    shared_llm = _make_llm(
        '{"intent": "qa"}',
        "Acesse o site da ANEF para renovar.",
    )
    monkeypatch.setattr(nodes_module, "_get_llm", lambda: shared_llm)
    monkeypatch.setattr(nodes_module, "_llm", None)
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
                    "date": "2024-05-01",
                    "category": "Visa & Residency",
                    "score": 0.92,
                }
            ]
        },
    )
    monkeypatch.setattr(tools_module, "_get_collection_name", lambda: "test")

    result = _run("Como renovar o titre de séjour em Grenoble?")

    assert result["intent"] == "qa"
    assert result["answer"] == "Acesse o site da ANEF para renovar."
    assert len(result["sources"]) == 1
    assert result["confidence"] > 0.0


# ── QA → RAG → empty search results ──────────────────────────────────────────


def test_qa_rag_empty_search_returns_fallback(monkeypatch):
    shared_llm = _make_llm('{"intent": "qa"}')
    monkeypatch.setattr(nodes_module, "_get_llm", lambda: shared_llm)
    monkeypatch.setattr(nodes_module, "_llm", None)
    monkeypatch.setattr(
        tools_module,
        "hybrid_search",
        lambda **_: {"chunks": []},
    )
    monkeypatch.setattr(tools_module, "_get_collection_name", lambda: "test")

    result = _run("Como é a vida em Grenoble no inverno com muita neve?")

    assert result["intent"] == "qa"
    assert "Não encontrei" in result["answer"]
    assert result["confidence"] == 0.0
    assert result["sources"] == []


# ── QA → RAG → search tool error ─────────────────────────────────────────────


def test_qa_rag_search_error_returns_fallback(monkeypatch):
    shared_llm = _make_llm('{"intent": "qa"}')
    monkeypatch.setattr(nodes_module, "_get_llm", lambda: shared_llm)
    monkeypatch.setattr(nodes_module, "_llm", None)
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
    monkeypatch.setattr(tools_module, "_get_collection_name", lambda: "test")

    result = _run("Como abrir conta no banco sendo estrangeiro?")

    assert result["intent"] == "qa"
    # search failed → context_chunks empty → fallback answer
    assert "Não encontrei" in result["answer"]


# ── Memory tests ──────────────────────────────────────────────────────────────


def test_memory_populated_after_run(monkeypatch):
    monkeypatch.setattr(
        nodes_module, "_get_llm", lambda: _make_llm('{"intent": "greeting"}')
    )
    monkeypatch.setattr(nodes_module, "_llm", None)

    _run("Oi!", chat_id="chat-mem")

    history = agent_module._get_history("chat-mem")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Oi!"
    assert history[1]["role"] == "assistant"


def test_memory_capped_at_max_history(monkeypatch):
    # Send 5 messages; memory should hold at most _MAX_HISTORY entries
    for i in range(5):
        monkeypatch.setattr(
            nodes_module, "_get_llm", lambda: _make_llm('{"intent": "greeting"}')
        )
        monkeypatch.setattr(nodes_module, "_llm", None)
        _run(f"Mensagem {i}", chat_id="chat-cap")

    history = agent_module._get_history("chat-cap")
    assert len(history) <= agent_module._MAX_HISTORY


def test_history_passed_into_initial_state(monkeypatch):
    # Seed memory manually and check it's included in the run
    agent_module._memory["chat-hist"] = {
        "messages": [
            {"role": "user", "content": "Oi"},
            {"role": "assistant", "content": "Olá!"},
        ],
        "category": "",
    }
    monkeypatch.setattr(
        nodes_module, "_get_llm", lambda: _make_llm('{"intent": "greeting"}')
    )
    monkeypatch.setattr(nodes_module, "_llm", None)

    # Just confirm the run doesn't crash with pre-populated history
    result = _run("Oi de novo!", chat_id="chat-hist")
    assert result["answer"]
