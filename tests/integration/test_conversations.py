"""Multi-turn conversation integration tests.

Each test simulates a realistic user session (1–3 turns).
All external calls (LLM + Qdrant) are mocked; no real services needed.

Scenarios mirror smoke_test.py so the same paths are covered by both
automated CI and manual end-to-end runs.
"""

from unittest.mock import MagicMock

import pytest

import habitantes.domain.agent as agent_module
import habitantes.domain.categories as categories_module
import habitantes.domain.nodes as nodes_module
import habitantes.domain.tools as tools_module
from habitantes.config import CategoryEntry

# ── Shared test categories (small, stable subset) ────────────────────────────

_CATS = [
    CategoryEntry(pt_name="Visto & Residência", en_name="Visa & Residency"),
    CategoryEntry(pt_name="Bancos & Finanças", en_name="Banking & Finance"),
    CategoryEntry(pt_name="Moradia & CAF", en_name="Housing & CAF"),
    CategoryEntry(pt_name="Saúde & Seguros", en_name="Health & Insurance"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────


def _llm_response(content: str) -> MagicMock:
    r = MagicMock()
    r.content = content
    return r


def _make_llm(*responses: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke.side_effect = [_llm_response(r) for r in responses]
    return llm


def _run(message: str, chat_id: str) -> dict:
    return agent_module.run(
        chat_id=chat_id,
        message=message,
        message_id="msg-test",
        trace_id="trace-test",
    )


def _mock_search(chunks: list | None = None) -> None:
    """Return a patched hybrid_search lambda (must call monkeypatch externally)."""
    return chunks or []


_CHUNK_VISA = {
    "text": "Para renovar o titre de séjour acesse o site da ANEF.",
    "question": "Como renovar o titre de séjour?",
    "answer": "Para renovar o titre de séjour acesse o site da ANEF.",
    "source": "ANEF",
    "date": "2024-05-01",
    "category": "Visa & Residency",
    "score": 0.92,
}

_CHUNK_CAF = {
    "text": "Para solicitar a CAF, crie uma conta no caf.fr.",
    "question": "Como conseguir a CAF?",
    "answer": "Para solicitar a CAF, crie uma conta no caf.fr.",
    "source": "CAF",
    "date": "2024-03-10",
    "category": "Housing & CAF",
    "score": 0.88,
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_memory():
    agent_module._memory.clear()
    yield
    agent_module._memory.clear()


@pytest.fixture(autouse=True)
def mock_categories(monkeypatch):
    monkeypatch.setattr(categories_module, "_get_categories", lambda: _CATS)
    monkeypatch.setattr(categories_module, "_categories_cache", None)


# ── Scenario A: Direct question ───────────────────────────────────────────────


def test_direct_question_no_category_filter(monkeypatch):
    """User sends a full question without selecting a category first.
    Search runs with categories=None (no filter).
    """
    captured = {}

    def _search(**kwargs):
        captured.update(kwargs)
        return {"chunks": [_CHUNK_VISA]}

    shared_llm = _make_llm('{"intent": "qa"}', "Acesse a ANEF para renovar.")
    monkeypatch.setattr(nodes_module, "_get_llm", lambda: shared_llm)
    monkeypatch.setattr(nodes_module, "_llm", None)
    monkeypatch.setattr(tools_module, "hybrid_search", _search)
    monkeypatch.setattr(tools_module, "_get_collection_name", lambda: "test")

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
    r1 = _run("1", chat_id="c-num-q")

    assert r1["intent"] == "qa"
    assert r1["category"] == "Visa & Residency"
    assert "Visto & Residência" in r1["answer"]  # contextual clarification
    assert r1["confidence"] == 0.5

    # ── Turn 2 ────────────────────────────────────────────────────────────────
    captured = {}

    def _search(**kwargs):
        captured.update(kwargs)
        return {"chunks": [_CHUNK_VISA]}

    shared_llm = _make_llm('{"intent": "qa"}', "Acesse a ANEF.")
    monkeypatch.setattr(nodes_module, "_get_llm", lambda: shared_llm)
    monkeypatch.setattr(nodes_module, "_llm", None)
    monkeypatch.setattr(tools_module, "hybrid_search", _search)
    monkeypatch.setattr(tools_module, "_get_collection_name", lambda: "test")

    r2 = _run("Como renovar o titre de séjour?", chat_id="c-num-q")

    assert r2["intent"] == "qa"
    assert r2["category"] == "Visa & Residency"  # loaded from memory
    assert r2["answer"] == "Acesse a ANEF."
    assert captured.get("categories") == ["Visa & Residency"]  # filter applied


# ── Scenario D: Greeting → number → question ──────────────────────────────────


def test_greeting_then_number_then_question(monkeypatch):
    """Full 3-turn happy path."""
    # ── Turn 1: greeting ──────────────────────────────────────────────────────
    monkeypatch.setattr(
        nodes_module, "_get_llm", lambda: _make_llm('{"intent": "greeting"}')
    )
    monkeypatch.setattr(nodes_module, "_llm", None)

    r1 = _run("Olá!", chat_id="c-full")
    assert r1["intent"] == "greeting"
    assert "1." in r1["answer"]  # numbered menu must appear
    assert "Visto & Residência" in r1["answer"]

    # ── Turn 2: pick category 3 (Housing & CAF) ───────────────────────────────
    r2 = _run("3", chat_id="c-full")

    assert r2["category"] == "Housing & CAF"
    assert "Moradia & CAF" in r2["answer"]

    # ── Turn 3: ask question ───────────────────────────────────────────────────
    shared_llm = _make_llm('{"intent": "qa"}', "Crie uma conta no caf.fr.")
    monkeypatch.setattr(nodes_module, "_get_llm", lambda: shared_llm)
    monkeypatch.setattr(nodes_module, "_llm", None)
    monkeypatch.setattr(
        tools_module, "hybrid_search", lambda **_: {"chunks": [_CHUNK_CAF]}
    )
    monkeypatch.setattr(tools_module, "_get_collection_name", lambda: "test")

    r3 = _run("Como conseguir a CAF?", chat_id="c-full")

    assert r3["intent"] == "qa"
    assert r3["category"] == "Housing & CAF"  # persisted from turn 2
    assert r3["answer"] == "Crie uma conta no caf.fr."


# ── Scenario E: Category switch ───────────────────────────────────────────────


def test_category_switch_before_asking(monkeypatch):
    """User picks category 1, then changes mind to category 4 before asking."""
    # Turn 1: pick 1
    r1 = _run("1", chat_id="c-switch")
    assert r1["category"] == "Visa & Residency"

    # Turn 2: change to 4
    r2 = _run("4", chat_id="c-switch")
    assert r2["category"] == "Health & Insurance"
    assert "Saúde & Seguros" in r2["answer"]

    # Turn 3: ask question — must use the LAST selected category
    captured = {}

    def _search(**kwargs):
        captured.update(kwargs)
        return {"chunks": []}

    shared_llm = _make_llm('{"intent": "qa"}')
    monkeypatch.setattr(nodes_module, "_get_llm", lambda: shared_llm)
    monkeypatch.setattr(nodes_module, "_llm", None)
    monkeypatch.setattr(tools_module, "hybrid_search", _search)
    monkeypatch.setattr(tools_module, "_get_collection_name", lambda: "test")

    _run("Como funciona a Sécurité Sociale?", chat_id="c-switch")
    assert captured.get("categories") == ["Health & Insurance"]


# ── Scenario I: Greeting resets category ──────────────────────────────────────


def test_greeting_resets_selected_category(monkeypatch):
    """After picking a category, sending a new greeting clears the selection."""
    # Turn 1: pick category 1
    _run("1", chat_id="c-reset")
    assert agent_module._get_selected_category("c-reset") == "Visa & Residency"

    # Turn 2: new greeting → category must be cleared
    monkeypatch.setattr(
        nodes_module, "_get_llm", lambda: _make_llm('{"intent": "greeting"}')
    )
    monkeypatch.setattr(nodes_module, "_llm", None)

    _run("Olá novamente!", chat_id="c-reset")
    assert agent_module._get_selected_category("c-reset") == ""

    # Turn 3: direct question → no category filter
    captured = {}

    def _search(**kwargs):
        captured.update(kwargs)
        return {"chunks": []}

    shared_llm = _make_llm('{"intent": "qa"}')
    monkeypatch.setattr(nodes_module, "_get_llm", lambda: shared_llm)
    monkeypatch.setattr(nodes_module, "_llm", None)
    monkeypatch.setattr(tools_module, "hybrid_search", _search)
    monkeypatch.setattr(tools_module, "_get_collection_name", lambda: "test")

    _run("Como abrir conta no banco?", chat_id="c-reset")
    assert captured.get("categories") is None  # category was cleared by greeting
