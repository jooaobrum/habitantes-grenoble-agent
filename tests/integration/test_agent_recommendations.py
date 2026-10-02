"""Agent-seam tests for the Recommendation Request path.

A scripted LLM drives the real ReAct loop; `search_suggestions` runs for real
against an in-memory Qdrant collection seeded with Cluster entries (through the
production loader, with a fake keyword embedder so no network/model is needed).
"""

import re
from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pytest
from langchain_core.messages import ToolMessage
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

import habitantes.domain.agent as agent_module
import habitantes.domain.tools.search as search_module
import habitantes.domain.tools.suggestions as suggestions_module
from habitantes.domain.suggestions import ClusterEntry, ClusterMember, Kind
from ingestion.load.suggestions import load_clusters

_VOCAB = ["pastel", "polvilho", "mandioca", "dent", "limpeza", "cabelo", "cacheado"]


def _fake_embed(text: str) -> list[float]:
    low = text.lower()
    vec = np.array([float(low.count(w)) for w in _VOCAB] + [0.3], dtype="float32")
    return (vec / np.linalg.norm(vec)).tolist()


def _fake_sparse(texts):
    return [qmodels.SparseVector(indices=[0], values=[1.0]) for _ in texts]


class ScriptedLLM:
    """Returns scripted responses in order; records bound tools and every prompt."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.bound: list[list[str]] = []
        self.prompts: list[list] = []

    def bind_tools(self, tools, **_):
        self.bound.append([t.name for t in tools])
        return self

    def invoke(self, msgs):
        self.prompts.append(list(msgs))
        r = self._responses.pop(0)
        if isinstance(r, str):
            resp = MagicMock()
            resp.content = r
            resp.tool_calls = []
            return resp
        return r

    def tool_messages(self) -> list[str]:
        last = self.prompts[-1]
        return [m.content for m in last if isinstance(m, ToolMessage)]


def _call(name: str, args: dict, call_id: str = "c1") -> MagicMock:
    resp = MagicMock()
    resp.content = ""
    resp.tool_calls = [{"name": name, "args": args, "id": call_id}]
    return resp


def _intent_llm(intent: str) -> MagicMock:
    resp = MagicMock()
    resp.content = ""
    resp.tool_calls = [
        {"name": "IntentClassification", "args": {"intent": intent}, "id": "i"}
    ]
    resp.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    llm = MagicMock()
    llm.invoke.return_value = resp
    return llm


def _run(message: str) -> dict:
    return agent_module.run(
        chat_id="chat-rec", message=message, message_id="m", trace_id="t"
    )


@pytest.fixture(autouse=True)
def _reset():
    agent_module._memory.clear()
    agent_module._llm = None
    agent_module._intent_llm = None
    yield
    agent_module._memory.clear()


@pytest.fixture
def qdrant(monkeypatch, seeded_clusters):
    client = QdrantClient(":memory:")
    name = "test_suggestions"
    monkeypatch.setattr(search_module, "_get_qdrant_client", lambda: client)
    monkeypatch.setattr(suggestions_module, "_embed_query", _fake_embed)
    monkeypatch.setattr(
        suggestions_module, "_collection_name", lambda: name, raising=False
    )
    return client, name


def _seed(qdrant, clusters):
    client, name = qdrant
    load_clusters(
        clusters,
        client,
        name,
        dense_embed=lambda texts: [_fake_embed(t) for t in texts],
        sparse_embed=_fake_sparse,
    )


def _script(monkeypatch, intent: str, *responses) -> ScriptedLLM:
    monkeypatch.setattr(agent_module, "_get_intent_llm", lambda: _intent_llm(intent))
    llm = ScriptedLLM(*responses)
    monkeypatch.setattr(agent_module, "_get_llm", lambda: llm)
    return llm


def _enable_web(monkeypatch, result="[1] resultado web") -> MagicMock:
    from habitantes.config import load_settings

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    load_settings.cache_clear()  # settings may already be cached by seeding
    web = MagicMock()
    web.name = "web_search_grenoble"
    web.invoke.return_value = {"results": [], "formatted": result}
    monkeypatch.setattr(agent_module, "get_web_search_tool", lambda: web)
    return web


def test_recommendation_binds_search_suggestions_and_feeds_cluster_to_llm(
    monkeypatch, qdrant, seeded_clusters
):
    _seed(qdrant, seeded_clusters)
    llm = _script(
        monkeypatch,
        "recommendation",
        _call(
            "search_suggestions", {"query": "onde compro massa de pastel e polvilho"}
        ),
        "Épicerie Tropical: 9👍/0👎, última menção 20/05/2026.",
    )

    result = _run("onde compro massa de pastel e polvilho?")

    assert result["intent"] == "recommendation"
    assert llm.bound[0] == ["search_suggestions"]
    (tool_msg,) = llm.tool_messages()
    assert "Épicerie Tropical" in tool_msg
    assert "9👍" in tool_msg and "0👎" in tool_msg
    assert "2026-05-20" in tool_msg
    assert result["answer"].startswith("Épicerie Tropical")
    assert result["error"] is None
    assert result["confidence"] > 0


def test_kind_filter_restricts_clusters(monkeypatch, qdrant, seeded_clusters):
    _seed(qdrant, seeded_clusters)
    llm = _script(
        monkeypatch,
        "recommendation",
        _call(
            "search_suggestions",
            {"query": "dentista limpeza dental", "kind": "Dentists"},
        ),
        "ok",
    )
    _run("indicação de dentista para limpeza")
    (tool_msg,) = llm.tool_messages()
    assert "Cabinet Dentaire Alpes" in tool_msg
    assert "Épicerie Tropical" not in tool_msg


def test_disliked_member_is_not_offered(monkeypatch, qdrant, seeded_clusters):
    """Clinique du Sourire has 2👍/2👎 (net 0): never offered as a recommendation."""
    _seed(qdrant, seeded_clusters)
    llm = _script(
        monkeypatch,
        "recommendation",
        _call("search_suggestions", {"query": "dentista"}),
        "ok",
    )
    _run("indicação de dentista")
    (tool_msg,) = llm.tool_messages()
    assert "Cabinet Dentaire Alpes" in tool_msg
    assert "Clinique du Sourire" not in tool_msg


def test_community_business_is_disclosed(monkeypatch, qdrant, seeded_clusters):
    _seed(qdrant, seeded_clusters)
    llm = _script(
        monkeypatch,
        "recommendation",
        _call("search_suggestions", {"query": "polvilho massa de pastel"}),
        "ok",
    )
    _run("onde compro polvilho e massa de pastel?")
    (tool_msg,) = llm.tool_messages()
    assert re.search(r"Sabor do Brasil \[negócio de membro da comunidade\]", tool_msg)


def test_results_capped_at_three_clusters_with_five_members_each(monkeypatch, qdrant):
    def cluster(i: int) -> ClusterEntry:
        return ClusterEntry(
            kind=Kind.DENTISTS,
            label=f"Dentista grupo {i}",
            thumbs_up=20,
            thumbs_down=0,
            last_date=date(2026, 1, 1),
            members=[
                ClusterMember(
                    name=f"Cabinet {i}-{j}",
                    thumbs_up=10 - j,
                    last_date=date(2026, 1, 1),
                    items=["limpeza dental"],
                )
                for j in range(10)
            ],
            summary="dentistas",
        )

    _seed(qdrant, [cluster(i) for i in range(5)])
    llm = _script(
        monkeypatch,
        "recommendation",
        _call("search_suggestions", {"query": "dentista limpeza dental"}),
        "ok",
    )
    _run("indicação de dentista")
    (tool_msg,) = llm.tool_messages()
    assert tool_msg.count("Grupo:") == 3
    # 5 top members per cluster; the long tail only appears when its Items
    # match the query (here every member's Items do, capped at 3 extras).
    assert tool_msg.count("- Cabinet") == 3 * 8


def test_no_results_signals_and_falls_back_to_web(monkeypatch, qdrant, seeded_clusters):
    _seed(qdrant, seeded_clusters)
    web = _enable_web(monkeypatch)
    llm = _script(
        monkeypatch,
        "recommendation",
        _call("search_suggestions", {"query": "conserto de bicicleta"}),
        _call("web_search_grenoble", {"query": "réparation vélo Grenoble"}, "c2"),
        "A comunidade não indicou nada; pela web: Vélo Atelier.",
    )

    result = _run("indicação de conserto de bicicleta")

    web.invoke.assert_called_once()
    assert "Nenhuma sugestão da comunidade" in llm.prompts[1][-1].content
    assert llm.bound[0] == ["search_suggestions", "web_search_grenoble"]
    assert "web" in result["answer"].lower()


def test_both_binds_kb_and_suggestion_tools_plus_web(
    monkeypatch, qdrant, seeded_clusters
):
    _seed(qdrant, seeded_clusters)
    _enable_web(monkeypatch)
    llm = _script(monkeypatch, "both", "resposta")
    _run("como traduzir meus documentos e qual dentista vocês indicam?")
    assert llm.bound[0] == [
        "search_knowledge_base",
        "list_knowledge_subcategories",
        "get_chunks_by_category",
        "search_suggestions",
        "web_search_grenoble",
    ]


def test_question_does_not_bind_search_suggestions(monkeypatch, qdrant):
    _enable_web(monkeypatch)
    llm = _script(monkeypatch, "qa", "resposta")
    _run("Como funciona o titre de séjour em Grenoble?")
    assert "search_suggestions" not in llm.bound[0]
    assert "web_search_grenoble" in llm.bound[0]


def test_recommendation_prompt_asks_for_name_votes_date_and_context(
    monkeypatch, qdrant
):
    llm = _script(monkeypatch, "recommendation", "ok")
    _run("indicação de dentista")
    system = llm.prompts[0][0].content
    assert "INTENT CLASSIFICADO: recommendation" in system
    assert "👍/👎" in system and "última menção" in system
    assert "search_knowledge_base" not in llm.bound[0]
