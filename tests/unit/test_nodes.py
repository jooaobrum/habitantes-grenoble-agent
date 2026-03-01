"""Unit tests for domain/nodes.py.

LLM calls are mocked via monkeypatch on _get_llm so tests run without
a real OpenAI API key and complete in milliseconds.
"""

from unittest.mock import MagicMock

import pytest

import habitantes.domain.nodes as nodes_module
from habitantes.domain.nodes import (
    classify_intent,
    generate_clarification,
    generate_decline,
    generate_greeting,
    generate_response,
    log_feedback,
    route,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_state(**overrides) -> dict:
    """Minimal valid AgentState for testing."""
    base = {
        "chat_id": "chat-1",
        "message": "Como renovar meu titre de séjour?",
        "message_id": "msg-1",
        "trace_id": "trace-abc",
        "intent": "",
        "category": "",
        "context_chunks": [],
        "answer": "",
        "sources": [],
        "confidence": 0.0,
        "history": [],
        "timings": {},
        "error": None,
    }
    base.update(overrides)
    return base


def _mock_llm(content: str) -> MagicMock:
    """Return a mock LLM whose .invoke() returns a response with .content."""
    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.invoke.return_value = response
    return llm


# ── classify_intent ───────────────────────────────────────────────────────────


class TestClassifyIntent:
    def test_returns_intent_from_llm(self, monkeypatch):
        monkeypatch.setattr(
            nodes_module, "_get_llm", lambda: _mock_llm('{"intent": "qa"}')
        )
        monkeypatch.setattr(nodes_module, "_llm", None)

        result = classify_intent(_make_state())

        assert result["intent"] == "qa"
        assert "intent_ms" in result["timings"]

    def test_fallback_on_invalid_json(self, monkeypatch):
        monkeypatch.setattr(
            nodes_module, "_get_llm", lambda: _mock_llm("not json at all")
        )
        monkeypatch.setattr(nodes_module, "_llm", None)

        result = classify_intent(_make_state())

        assert result["intent"] == "out_of_scope"

    def test_preserves_existing_timings(self, monkeypatch):
        monkeypatch.setattr(
            nodes_module, "_get_llm", lambda: _mock_llm('{"intent": "greeting"}')
        )
        monkeypatch.setattr(nodes_module, "_llm", None)

        state = _make_state(timings={"category_ms": 50.0})
        result = classify_intent(state)

        assert result["timings"]["category_ms"] == 50.0
        assert "intent_ms" in result["timings"]

    @pytest.mark.parametrize("intent", ["greeting", "qa", "feedback", "out_of_scope"])
    def test_all_valid_intents(self, monkeypatch, intent):
        monkeypatch.setattr(
            nodes_module, "_get_llm", lambda: _mock_llm(f'{{"intent": "{intent}"}}')
        )
        monkeypatch.setattr(nodes_module, "_llm", None)

        result = classify_intent(_make_state())

        assert result["intent"] == intent


# ── route ─────────────────────────────────────────────────────────────────────


class TestRoute:
    def test_short_message_returns_clarify(self):
        state = _make_state(message="visto")
        assert route(state) == "clarify"

    def test_normal_message_returns_rag(self):
        state = _make_state(message="Como renovar o titre de séjour em Grenoble?")
        assert route(state) == "rag"

    def test_exactly_ten_chars_returns_rag(self):
        state = _make_state(message="1234567890")
        assert route(state) == "rag"

    def test_whitespace_only_returns_clarify(self):
        state = _make_state(message="   ")
        assert route(state) == "clarify"


# ── generate_response ─────────────────────────────────────────────────────────


class TestGenerateResponse:
    _chunks = [
        {
            "text": "Para renovar acesse a ANEF.",
            "category": "Visa & Residency",
            "date": "2024-05-01",
            "score": 0.92,
        },
        {
            "text": "O agendamento demora meses.",
            "category": "Visa & Residency",
            "date": "2024-06-01",
            "score": 0.85,
        },
    ]

    def test_returns_answer_from_llm(self, monkeypatch):
        monkeypatch.setattr(
            nodes_module, "_get_llm", lambda: _mock_llm("Aqui está a resposta.")
        )
        monkeypatch.setattr(nodes_module, "_llm", None)

        state = _make_state(context_chunks=self._chunks)
        result = generate_response(state)

        assert result["answer"] == "Aqui está a resposta."
        assert len(result["sources"]) == 2
        assert result["confidence"] == pytest.approx(0.92)
        assert "generation_ms" in result["timings"]

    def test_empty_chunks_returns_fallback(self, monkeypatch):
        monkeypatch.setattr(nodes_module, "_llm", None)

        state = _make_state(context_chunks=[])
        result = generate_response(state)

        assert "Não encontrei informações confiáveis" in result["answer"]
        assert result["sources"] == []
        assert result["confidence"] == 0.0

    def test_sources_contain_required_fields(self, monkeypatch):
        monkeypatch.setattr(nodes_module, "_get_llm", lambda: _mock_llm("Resposta."))
        monkeypatch.setattr(nodes_module, "_llm", None)

        state = _make_state(context_chunks=self._chunks)
        result = generate_response(state)

        for src in result["sources"]:
            assert "text_snippet" in src
            assert "date" in src
            assert "category" in src

    def test_confidence_capped_at_1(self, monkeypatch):
        monkeypatch.setattr(nodes_module, "_get_llm", lambda: _mock_llm("Resposta."))
        monkeypatch.setattr(nodes_module, "_llm", None)

        chunks = [
            {"text": "x", "category": "General", "date": "2024-01-01", "score": 1.5}
        ]
        state = _make_state(context_chunks=chunks)
        result = generate_response(state)

        assert result["confidence"] <= 1.0


# ── Static nodes ─────────────────────────────────────────────────────────────


class TestStaticNodes:
    def test_generate_greeting_returns_answer(self):
        result = generate_greeting(_make_state())
        assert isinstance(result["answer"], str)
        assert len(result["answer"]) > 0
        assert result["confidence"] == 1.0

    def test_generate_decline_returns_answer(self):
        result = generate_decline(_make_state())
        assert isinstance(result["answer"], str)
        assert len(result["answer"]) > 0
        assert result["confidence"] == 1.0

    def test_generate_clarification_returns_answer(self):
        result = generate_clarification(_make_state())
        assert isinstance(result["answer"], str)
        assert len(result["answer"]) > 0
        assert result["confidence"] == 0.5

    def test_log_feedback_returns_answer(self):
        result = log_feedback(_make_state(message="👍"))
        assert isinstance(result["answer"], str)
        assert len(result["answer"]) > 0
