"""Ingestion seam: Mentions file -> Suggestions file -> Cluster points.

The merge/label LLM is mocked at the HTTP layer (httpx.MockTransport), embeddings
are stubbed and Qdrant is in-memory. Assertions are on what ends up stored.
"""

import asyncio
import json
import os
from datetime import date

import httpx
import numpy as np
import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from habitantes.config import SuggestionsConfig
from habitantes.domain.suggestions import Kind
from ingestion.config import MentionExtractionConfig
from ingestion.suggestions.build import run_suggestions_builder
from ingestion.suggestions.clusters import cluster_mentions
from ingestion.suggestions.extract import Mention
from ingestion.suggestions.suggestions import SUGGESTIONS_FILENAME, read_suggestions

os.environ.setdefault("OPENROUTER_API_KEY", "test")

TODAY = date(2026, 10, 2)
COLLECTION = "suggestions_test"


def M(
    name,
    when,
    polarity="positive",
    kind="Markets & Groceries",
    items=(),
    ctx="Bom.",
    cb=False,
):
    return Mention(
        name=name,
        kind=Kind(kind),
        polarity=polarity,
        items=list(items),
        context=ctx,
        date=date.fromisoformat(when),
        community_business=cb,
    )


MENTIONS = [
    # one chain written three ways, one branch named
    M("Gran Free", "2025-01-10", items=["frutas"]),
    M("Grand Frais Échirolles", "2025-05-02", items=["carne"]),
    M("grand frais", "2023-01-05"),  # older than 2 years: half weight
    M("Grand Frais", "2026-02-01", "negative", ctx="Fila enorme."),
    M("Épicerie Tropical", "2026-05-20", items=["polvilho", "farinha de mandioca"]),
    M("Epicerie  Tropical!", "2026-01-01", items=["massa de pastel"]),
    M("Mercado Ruim", "2026-03-01", "negative"),
    M("Mercado Ruim", "2026-03-02", "negative"),
    M("Loja Antiga", "2020-01-01"),  # half weight but still > 0
    M("Alpha", "2026-04-01"),
    M("Beta", "2026-06-01"),
    M("Gama", "2026-07-01"),
    M("Delta", "2026-08-01"),
    # community business: only the advertiser's post -> never offered
    M("Sabor do Brasil", "2026-05-05", cb=True),
    # community business with a Mention from another member -> flagged, 1 vote
    M("Casa Brasil", "2026-05-06", cb=True),
    M("Casa Brasil", "2026-05-07"),
    M(
        "Cabinet Dentaire Alpes",
        "2026-02-08",
        kind="Dentists",
        items=["limpeza dental"],
    ),
]


class Emb:
    def __init__(self):
        self.dense_texts = []

    def dense(self, texts):
        self.dense_texts += texts
        return [np.ones(4).tolist() for _ in texts]

    def sparse(self, texts):
        return [qmodels.SparseVector(indices=[0], values=[1.0]) for _ in texts]


def _llm(prompts):
    def handler(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        prompts.append(prompt)
        if "Agrupe" in prompt:
            groups = []
            if '"Markets & Groceries"' in prompt:
                groups = [
                    {
                        "canonical": "Grand Frais",
                        "variants": [
                            "Gran Free",
                            "Grand Frais Échirolles",
                            "grand frais",
                        ],
                    }
                ]
            content = {"groups": groups}
        else:
            content = {
                "label": "Rótulo do grupo",
                "lines": {"Grand Frais": "bom para frutas"},
            }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
        )

    return handler


def _run(tmp_path, mentions=MENTIONS, cfg=None, client=None, emb=None, prompts=None):
    path = tmp_path / "mentions.jsonl"
    path.write_text(
        "".join(m.model_dump_json() + "\n" for m in mentions), encoding="utf-8"
    )
    client = client or QdrantClient(":memory:")
    emb = emb or Emb()
    prompts = prompts if prompts is not None else []

    async def go():
        lc = httpx.AsyncClient(transport=httpx.MockTransport(_llm(prompts)))
        try:
            return await run_suggestions_builder(
                path,
                tmp_path,
                cfg or SuggestionsConfig(collection_name=COLLECTION),
                MentionExtractionConfig(max_retries=1, retry_base_sleep_s=0),
                qclient=client,
                llm_client=lc,
                dense_embed=emb.dense,
                sparse_embed=emb.sparse,
                today=TODAY,
            )
        finally:
            await lc.aclose()

    return asyncio.run(go()), client, emb


def _points(client):
    pts, _ = client.scroll(COLLECTION, limit=50, with_payload=True)
    return {p.payload["kind"]: p.payload for p in pts}


def test_one_cluster_per_kind_with_merged_chain_counts_and_dates(tmp_path):
    n, client, _ = _run(tmp_path)
    clusters = _points(client)
    assert n == 2 and set(clusters) == {"Markets & Groceries", "Dentists"}
    market = clusters["Markets & Groceries"]
    assert (
        market["topic"] == "Food & Restaurants" and market["label"] == "Rótulo do grupo"
    )
    gf = [m for m in market["members"] if "frais" in m["name"].lower()]
    assert len(gf) == 1  # chain + variants = one Suggestion
    assert gf[0]["name"] == "Grand Frais"
    assert (gf[0]["thumbs_up"], gf[0]["thumbs_down"]) == (3, 1)
    assert gf[0]["last_date"] == "2026-02-01"
    assert set(gf[0]["items"]) == {"frutas", "carne"}
    tropical = next(m for m in market["members"] if "Tropical" in m["name"])
    assert (tropical["thumbs_up"], tropical["last_date"]) == (2, "2026-05-20")
    assert tropical["name"].count("Tropical") == 1


def test_half_weight_ranking_ties_and_long_tail_retention(tmp_path):
    _, client, _ = _run(tmp_path)
    market = _points(client)["Markets & Groceries"]
    names = [m["name"] for m in market["members"]]
    # Tropical 2.0, Grand Frais 1+1+0.5-1 = 1.5, then 1-vote members by recency, old last
    assert names[:2] == ["Épicerie Tropical", "Grand Frais"]
    assert names[2:7] == ["Delta", "Gama", "Beta", "Casa Brasil", "Alpha"]
    assert names[7] == "Loja Antiga"  # 0.5: kept, ranked last of the positives
    # disliked member: stored, but not in the summary
    assert "Mercado Ruim" in names and "Mercado Ruim" not in market["summary"]
    # top 5 + "+K outras" (8 positive members -> 3 more)
    assert "+3 outras" in market["summary"]
    assert "Alpha" not in market["summary"] and "Loja Antiga" not in market["summary"]
    assert (market["thumbs_up"], market["thumbs_down"]) == (11, 3)


def test_community_business_needs_a_mention_from_another_member(tmp_path):
    _, client, _ = _run(tmp_path)
    members = {m["name"]: m for m in _points(client)["Markets & Groceries"]["members"]}
    assert "Sabor do Brasil" not in members
    assert members["Casa Brasil"]["community_business"] is True
    assert members["Casa Brasil"]["thumbs_up"] == 1


def test_items_and_names_reach_embedded_text(tmp_path):
    _, _, emb = _run(tmp_path)
    market_text = next(
        t for t in emb.dense_texts if "polvilho" in t and "massa de pastel" in t
    )
    for item in ("farinha de mandioca", "massa de pastel", "frutas", "carne"):
        assert item in market_text
    assert "bom para frutas" in market_text  # LLM-written summary line is embedded


def test_merge_pass_runs_once_per_kind_before_counting(tmp_path):
    prompts = []
    _run(tmp_path, prompts=prompts)
    merges = [p for p in prompts if "Agrupe" in p]
    assert len(merges) == 1  # Dentists has a single name: no call needed
    assert "Gran Free" in merges[0]


def test_author_free_files_and_payloads(tmp_path):
    _, client, _ = _run(tmp_path)
    stored = (tmp_path / SUGGESTIONS_FILENAME).read_text(encoding="utf-8")
    dumped = stored + json.dumps(_points(client))
    for forbidden in ("author", "phone", "user", "+33"):
        assert forbidden not in dumped
    sugg = read_suggestions(tmp_path / SUGGESTIONS_FILENAME)
    gf = next(s for s in sugg if s.name == "Grand Frais")
    assert (gf.thumbs_up, gf.thumbs_down, len(gf.mentions)) == (3, 1, 4)
    assert gf.topic.value == "Food & Restaurants"


def test_rebuild_from_suggestions_file_without_mentions(tmp_path):
    _, client, _ = _run(tmp_path)
    before = _points(client)
    (tmp_path / "mentions.jsonl").unlink()

    async def go():
        lc = httpx.AsyncClient(transport=httpx.MockTransport(_llm([])))
        try:
            return await run_suggestions_builder(
                tmp_path / "mentions.jsonl",
                tmp_path,
                SuggestionsConfig(collection_name=COLLECTION),
                MentionExtractionConfig(max_retries=1, retry_base_sleep_s=0),
                qclient=client,
                llm_client=lc,
                dense_embed=Emb().dense,
                sparse_embed=Emb().sparse,
                today=TODAY,
                from_suggestions_file=True,
            )
        finally:
            await lc.aclose()

    assert asyncio.run(go()) == 2
    after = _points(client)
    assert {k: [m["name"] for m in v["members"]] for k, v in after.items()} == {
        k: [m["name"] for m in v["members"]] for k, v in before.items()
    }


def test_qa_collection_untouched(tmp_path):
    client = QdrantClient(":memory:")
    client.create_collection(
        "qa_kb",
        vectors_config={
            "dense": qmodels.VectorParams(size=4, distance=qmodels.Distance.COSINE)
        },
    )
    client.upsert(
        "qa_kb",
        points=[
            qmodels.PointStruct(id=1, vector={"dense": [1, 0, 0, 0]}, payload={"q": 1})
        ],
    )
    _run(tmp_path, client=client)
    pts, _ = client.scroll("qa_kb", limit=5, with_payload=True)
    assert [(p.id, p.payload) for p in pts] == [(1, {"q": 1})]


def test_llm_failure_falls_back_to_normalised_names_and_kind_label(tmp_path):
    async def go():
        path = tmp_path / "m.jsonl"
        path.write_text("".join(m.model_dump_json() + "\n" for m in MENTIONS[:6]))
        lc = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(500))
        )
        client = QdrantClient(":memory:")
        try:
            await run_suggestions_builder(
                path,
                tmp_path,
                SuggestionsConfig(collection_name=COLLECTION),
                MentionExtractionConfig(max_retries=1, retry_base_sleep_s=0),
                qclient=client,
                llm_client=lc,
                dense_embed=Emb().dense,
                sparse_embed=Emb().sparse,
                today=TODAY,
            )
        finally:
            await lc.aclose()
        return client

    market = _points(asyncio.run(go()))["Markets & Groceries"]
    assert market["label"] == "Markets & Groceries"
    assert sum("ropical" in m["name"] for m in market["members"]) == 1


def _purpose_embed(texts):
    vocab = ["brasil", "mala", "viagem"]
    out = []
    for t in texts:
        v = np.array([t.lower().count(w) for w in vocab] + [0.01], dtype="float32")
        out.append((v / np.linalg.norm(v)).tolist())
    return out


def test_few_mentions_yield_a_single_cluster_and_none_yield_nothing():
    ms = [m for m in MENTIONS if m.kind == Kind.DENTISTS]
    assert cluster_mentions(Kind.DENTISTS, ms, _purpose_embed, 0.75) == [ms]
    assert cluster_mentions(Kind.DENTISTS, [], _purpose_embed, 0.75) == []


def test_mentions_group_by_purpose_not_by_shop():
    ms = [
        M("Casa X", "2026-01-01", items=["produtos brasil"], ctx="brasil"),
        M("Loja Y", "2026-01-02", items=["produtos brasil"], ctx="brasil"),
        M("Casa X", "2026-01-03", items=["mala viagem"], ctx="mala"),
        M("Loja Z", "2026-01-04", items=["mala viagem"], ctx="viagem"),
    ]
    groups = cluster_mentions(Kind.MARKETS_AND_GROCERIES, ms, _purpose_embed, 0.75)
    assert len(groups) == 2
    assert sorted(len(g) for g in groups) == [2, 2]
    assert all(len({m.items[0] for m in g}) == 1 for g in groups)


def test_shop_recommended_for_two_purposes_is_found_through_either(
    tmp_path, monkeypatch
):
    suggestions_module = pytest.importorskip("habitantes.domain.tools.suggestions")
    import habitantes.domain.tools.search as search_module

    ms = [
        M("Casa X", "2026-01-01", items=["produtos brasil"], ctx="brasil"),
        M("Loja Y", "2026-01-02", items=["produtos brasil"], ctx="brasil"),
        M("Casa X", "2026-01-03", items=["mala viagem"], ctx="mala"),
        M("Loja Z", "2026-01-04", items=["mala viagem"], ctx="viagem"),
    ]
    vocab = ["brasil", "mala", "viagem"]

    def embed(text):
        v = np.array([text.lower().count(w) for w in vocab] + [0.01], dtype="float32")
        return (v / np.linalg.norm(v)).tolist()

    emb = Emb()
    emb.dense = lambda texts: [embed(t) for t in texts]
    client = QdrantClient(":memory:")
    _run(tmp_path, mentions=ms, client=client, emb=emb)
    pts, _ = client.scroll(COLLECTION, limit=50, with_payload=True)
    assert len(pts) == 2
    assert len({p.payload["label"] for p in pts}) == 2  # unique per Kind
    for p in pts:
        names = [m["name"] for m in p.payload["members"]]
        assert names.count("Casa X") == 1  # repeated Mentions collapse per Cluster

    monkeypatch.setattr(search_module, "_get_qdrant_client", lambda: client)
    monkeypatch.setattr(suggestions_module, "_embed_query", embed)
    monkeypatch.setattr(
        suggestions_module, "_collection_name", lambda: COLLECTION, raising=False
    )
    for query in ("produtos brasil", "mala viagem"):
        out = suggestions_module.search_clusters(query)
        assert "Casa X" in out["formatted"]
        assert "Casa X" in [m["name"] for m in out["clusters"][0]["members"]]


def test_agent_search_over_the_loaded_collection(tmp_path, monkeypatch):
    suggestions_module = pytest.importorskip("habitantes.domain.tools.suggestions")
    import habitantes.domain.tools.search as search_module

    vocab = ["polvilho", "pastel", "dent", "frutas"]

    def embed(text):
        v = np.array([text.lower().count(w) for w in vocab] + [0.3], dtype="float32")
        return (v / np.linalg.norm(v)).tolist()

    client = QdrantClient(":memory:")
    emb = Emb()
    emb.dense = lambda texts: [embed(t) for t in texts]
    _run(
        tmp_path,
        client=client,
        emb=emb,
        cfg=SuggestionsConfig(collection_name=COLLECTION, similarity_cutoff=-1.0),
    )
    monkeypatch.setattr(search_module, "_get_qdrant_client", lambda: client)
    monkeypatch.setattr(suggestions_module, "_embed_query", embed)
    monkeypatch.setattr(
        suggestions_module, "_collection_name", lambda: COLLECTION, raising=False
    )

    out = suggestions_module.search_clusters("onde compro polvilho")
    assert "clusters" in out
    top = out["clusters"][0]
    assert top["kind"] == "Markets & Groceries"
    shown = [m["name"] for m in top["members"]]
    assert "Grand Frais" in shown and "Mercado Ruim" not in shown
    assert "Épicerie Tropical" in out["formatted"] or "Epicerie" in out["formatted"]
