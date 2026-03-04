"""Multi-turn conversation integration tests (ReAct architecture).

Each test simulates a realistic user session (1–3 turns).
All external calls (LLM + Qdrant) are mocked; no real services needed.

Tests mock agent_module._get_llm (since the ReAct agent uses
the same LLM factory for both intent classification and response generation).
"""

from unittest.mock import MagicMock

import pytest

import habitantes.domain.agent as agent_module
import habitantes.domain.categories as categories_module
import habitantes.domain.tools.search as tools_module
from habitantes.config import CategoryEntry

# ── Shared test categories (small, stable subset) ────────────────────────────

_CATS = [
    CategoryEntry(pt_name="Visto & Residência", en_name="Visa & Residency"),
    CategoryEntry(pt_name="Bancos & Finanças", en_name="Banking & Finance"),
    CategoryEntry(pt_name="Moradia & CAF", en_name="Housing & CAF"),
    CategoryEntry(pt_name="Saúde & Seguros", en_name="Health & Insurance"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────


def _ai_response(content: str, tool_calls=None) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.tool_calls = tool_calls or []
    return resp


def _make_llm(*responses) -> MagicMock:
    """LLM mock whose .invoke() returns successive responses."""
    llm = MagicMock()
    mocks = []
    for r in responses:
        if isinstance(r, str):
            mocks.append(_ai_response(r))
        else:
            mocks.append(r)
    llm.invoke.side_effect = mocks
    llm.bind_tools = MagicMock(return_value=llm)
    return llm


def _run(message: str, chat_id: str) -> dict:
    return agent_module.run(
        chat_id=chat_id,
        message=message,
        message_id="msg-test",
        trace_id="trace-test",
    )


_CHUNK_VISA = {
    "text": "Para renovar o titre de séjour acesse o site da ANEF.",
    "question": "Como renovar o titre de séjour?",
    "answer": "Para renovar o titre de séjour acesse o site da ANEF.",
    "source": "ANEF",
    "thread_id": 111,
    "date": "2024-05-01",
    "category": "Visa & Residency",
    "score": 0.92,
}

_CHUNK_CAF = {
    "text": "Para solicitar a CAF, crie uma conta no caf.fr.",
    "question": "Como conseguir a CAF?",
    "answer": "Para solicitar a CAF, crie uma conta no caf.fr.",
    "source": "CAF",
    "thread_id": 222,
    "date": "2024-03-10",
    "category": "Housing & CAF",
    "score": 0.88,
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_memory():
    agent_module._memory.clear()
    agent_module._llm = None
    yield
    agent_module._memory.clear()
    agent_module._llm = None


@pytest.fixture(autouse=True)
def mock_categories(monkeypatch):
    monkeypatch.setattr(categories_module, "_get_categories", lambda: _CATS)
    monkeypatch.setattr(categories_module, "_categories_cache", None)


# ── Scenario A: Direct question ───────────────────────────────────────────────


def test_direct_question_no_category_filter(monkeypatch):
    """User sends a full question without selecting a category first."""
    captured = {}

    def _search(**kwargs):
        captured.update(kwargs)
        return {"chunks": [_CHUNK_VISA]}

    tool_call = _ai_response(
        "",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"query": "Como renovar o titre de séjour em Grenoble?"},
                "id": "call_1",
            }
        ],
    )
    shared_llm = _make_llm(
        '{"intent": "qa"}',  # Layer 1
        tool_call,  # Layer 2: search
        "Acesse a ANEF para renovar.",  # Layer 2: final answer
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    mock_tool = MagicMock()
    mock_tool.name = "search_knowledge_base"
    mock_tool.invoke.return_value = "[1] Info visa"
    monkeypatch.setattr(tools_module, "get_search_tool", lambda: mock_tool)
    monkeypatch.setattr(tools_module, "hybrid_search", _search)

    result = _run("Como renovar o titre de séjour em Grenoble?", chat_id="c-direct")

    assert result["intent"] == "qa"
    assert result["answer"] == "Acesse a ANEF para renovar."
    assert result["confidence"] > 0.0
    # No category was selected → search must receive None
    assert captured.get("categories") is None


# ── Scenario C: Number → question ─────────────────────────────────────────────


def test_number_selection_then_question(monkeypatch):
    """Turn 1: user types '1' → bot names the category and asks for the question.
    Turn 2: user asks; category from turn 1 is passed to the search filter.
    """
    # ── Turn 1 ────────────────────────────────────────────────────────────────
    # Number shortcut bypasses intent LLM; ReAct responds with clarification
    llm_turn1 = _make_llm(
        "Ótimo! Você escolheu *Visto & Residência*. Qual é a sua dúvida?",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: llm_turn1)

    r1 = _run("1", chat_id="c-num-q")
    assert r1["intent"] == "qa"
    assert r1["category"] == "Visa & Residency"
    assert len(r1["answer"]) > 0

    # ── Turn 2 ────────────────────────────────────────────────────────────────
    captured = {}

    def _search(**kwargs):
        captured.update(kwargs)
        return {"chunks": [_CHUNK_VISA]}

    tool_call = _ai_response(
        "",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"query": "Como renovar o titre de séjour?"},
                "id": "call_2",
            }
        ],
    )
    shared_llm = _make_llm(
        '{"intent": "qa"}',
        tool_call,
        "Acesse a ANEF.",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    mock_tool = MagicMock()
    mock_tool.name = "search_knowledge_base"
    mock_tool.invoke.return_value = "[1] Info visa"
    monkeypatch.setattr(tools_module, "get_search_tool", lambda: mock_tool)
    monkeypatch.setattr(tools_module, "hybrid_search", _search)

    r2 = _run("Como renovar o titre de séjour?", chat_id="c-num-q")

    assert r2["intent"] == "qa"
    assert r2["category"] == "Visa & Residency"
    assert r2["answer"] == "Acesse a ANEF."
    assert captured.get("categories") == ["Visa & Residency"]


# ── Scenario D: Greeting → number → question ──────────────────────────────────


def test_greeting_then_number_then_question(monkeypatch):
    """Full 3-turn happy path."""
    # ── Turn 1: greeting ──────────────────────────────────────────────────────
    shared_llm = _make_llm(
        '{"intent": "greeting"}',
        "Olá! 1. Visto & Residência\n2. Bancos & Finanças",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    r1 = _run("Olá!", chat_id="c-full")
    assert r1["intent"] == "greeting"

    # ── Turn 2: pick category 3 (Housing & CAF) ───────────────────────────────
    llm_turn2 = _make_llm(
        "Ótimo! Você escolheu *Moradia & CAF*. Qual é a sua dúvida?",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: llm_turn2)

    r2 = _run("3", chat_id="c-full")
    assert r2["category"] == "Housing & CAF"

    # ── Turn 3: ask question ───────────────────────────────────────────────────
    tool_call = _ai_response(
        "",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"query": "Como conseguir a CAF?"},
                "id": "call_3",
            }
        ],
    )
    shared_llm = _make_llm(
        '{"intent": "qa"}',
        tool_call,
        "Crie uma conta no caf.fr.",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    mock_tool = MagicMock()
    mock_tool.name = "search_knowledge_base"
    mock_tool.invoke.return_value = "[1] Info CAF"
    monkeypatch.setattr(tools_module, "get_search_tool", lambda: mock_tool)
    monkeypatch.setattr(
        tools_module, "hybrid_search", lambda **_: {"chunks": [_CHUNK_CAF]}
    )

    r3 = _run("Como conseguir a CAF?", chat_id="c-full")

    assert r3["intent"] == "qa"
    assert r3["category"] == "Housing & CAF"
    assert r3["answer"] == "Crie uma conta no caf.fr."


# ── Scenario E: Category switch ───────────────────────────────────────────────


def test_category_switch_before_asking(monkeypatch):
    """User picks category 1, then changes mind to category 4 before asking."""
    # Turn 1: pick 1
    llm_turn1 = _make_llm(
        "Ótimo! Você escolheu *Visto & Residência*. Qual é a sua dúvida?",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: llm_turn1)
    r1 = _run("1", chat_id="c-switch")
    assert r1["category"] == "Visa & Residency"

    # Turn 2: change to 4
    llm_turn2 = _make_llm(
        "Ótimo! Você escolheu *Saúde & Seguros*. Qual é a sua dúvida?",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: llm_turn2)
    r2 = _run("4", chat_id="c-switch")
    assert r2["category"] == "Health & Insurance"

    # Turn 3: ask question — must use the LAST selected category
    captured = {}

    def _search(**kwargs):
        captured.update(kwargs)
        return {"chunks": []}

    tool_call = _ai_response(
        "",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"query": "Como funciona a Sécurité Sociale?"},
                "id": "call_4",
            }
        ],
    )
    shared_llm = _make_llm(
        '{"intent": "qa"}',
        tool_call,
        "Não encontrei informação confiável.",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    mock_tool = MagicMock()
    mock_tool.name = "search_knowledge_base"
    mock_tool.invoke.return_value = "Nenhum resultado."
    monkeypatch.setattr(tools_module, "get_search_tool", lambda: mock_tool)
    monkeypatch.setattr(tools_module, "hybrid_search", _search)

    _run("Como funciona a Sécurité Sociale?", chat_id="c-switch")
    assert captured.get("categories") == ["Health & Insurance"]


# ── Scenario I: Greeting resets category ──────────────────────────────────────


def test_greeting_resets_selected_category(monkeypatch):
    """After picking a category, sending a new greeting clears the selection."""
    # Turn 1: pick category 1
    llm_turn1 = _make_llm(
        "Ótimo! Você escolheu *Visto & Residência*. Qual é a sua dúvida?",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: llm_turn1)
    _run("1", chat_id="c-reset")
    assert agent_module._get_selected_category("c-reset") == "Visa & Residency"

    # Turn 2: new greeting → category must be cleared
    shared_llm = _make_llm(
        '{"intent": "greeting"}',
        "Olá novamente!",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    _run("Olá novamente!", chat_id="c-reset")
    assert agent_module._get_selected_category("c-reset") == ""

    # Turn 3: direct question → no category filter
    captured = {}

    def _search(**kwargs):
        captured.update(kwargs)
        return {"chunks": []}

    tool_call = _ai_response(
        "",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"query": "Como abrir conta no banco?"},
                "id": "call_5",
            }
        ],
    )
    shared_llm = _make_llm(
        '{"intent": "qa"}',
        tool_call,
        "Não encontrei informação.",
    )
    monkeypatch.setattr(agent_module, "_get_llm", lambda: shared_llm)

    mock_tool = MagicMock()
    mock_tool.name = "search_knowledge_base"
    mock_tool.invoke.return_value = "Nenhum resultado."
    monkeypatch.setattr(tools_module, "get_search_tool", lambda: mock_tool)
    monkeypatch.setattr(tools_module, "hybrid_search", _search)

    _run("Como abrir conta no banco?", chat_id="c-reset")
    assert captured.get("categories") is None
