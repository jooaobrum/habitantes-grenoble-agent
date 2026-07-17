"""Unit tests for T4 — token/cost capture on the chat path (agent.py).

Cost tracking reads `usage_metadata` off each LLM response, sums it per turn,
and computes `cost_usd` from `settings.pricing`. Missing usage metadata must
degrade to `0` without ever failing the turn.
"""

from unittest.mock import MagicMock

import pytest

import habitantes.domain.agent as agent_module
from habitantes.config import load_settings


def _ai_response(content: str, usage=None, tool_calls=None) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.tool_calls = tool_calls or []
    resp.usage_metadata = usage
    return resp


def _make_llm(*responses) -> MagicMock:
    llm = MagicMock()
    llm.invoke.side_effect = list(responses)
    llm.bind_tools = MagicMock(return_value=llm)
    return llm


def _run(message: str, chat_id: str = "chat-cost") -> dict:
    return agent_module.run(
        chat_id=chat_id, message=message, message_id="msg-1", trace_id="trace-1"
    )


@pytest.fixture(autouse=True)
def clear_singletons():
    agent_module._memory.clear()
    agent_module._llm = None
    yield
    agent_module._memory.clear()
    agent_module._llm = None


def test_usage_metadata_summed_across_turn(monkeypatch):
    """Classification + ReAct usage sum into tokens_in/out; cost from pricing."""
    shared_llm = _make_llm(
        _ai_response(
            '{"intent": "greeting"}',
            usage={"input_tokens": 100, "output_tokens": 50},
        ),
        _ai_response(
            "Olá! Bem-vindo.",
            usage={"input_tokens": 200, "output_tokens": 80},
        ),
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Olá!")

    assert result["tokens_in"] == 300
    assert result["tokens_out"] == 130

    pricing = load_settings().pricing
    expected = (
        300 * pricing.input_per_1m_usd / 1_000_000
        + 130 * pricing.output_per_1m_usd / 1_000_000
    )
    assert result["cost_usd"] == pytest.approx(expected)


def test_missing_usage_metadata_yields_zero(monkeypatch):
    """A response without usage_metadata → 0 tokens, 0 cost, turn still succeeds."""
    shared_llm = _make_llm(
        _ai_response('{"intent": "greeting"}', usage=None),
        _ai_response("Olá!", usage=None),
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    result = _run("Olá!")

    assert result["tokens_in"] == 0
    assert result["tokens_out"] == 0
    assert result["cost_usd"] == 0.0
    assert result["answer"] == "Olá!"
    assert result["error"] is None
