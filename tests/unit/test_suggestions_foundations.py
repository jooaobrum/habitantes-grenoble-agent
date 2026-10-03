import pytest
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from habitantes.config import SuggestionsConfig, load_settings
from habitantes.domain.categories import _get_categories
from habitantes.domain.suggestions import (
    KIND_TOPIC,
    ClusterEntry,
    Kind,
    topic_for_kind,
)
from ingestion.config import load_ingestion_settings
from ingestion.load.suggestions import load_clusters

EXPECTED_TOPICS = {
    "Restaurants & Bars": "Food & Restaurants",
    "Markets & Groceries": "Food & Restaurants",
    "Shops": "Daily Life & Services",
    "Products": "Daily Life & Services",
    "Professional Services": "Daily Life & Services",
    "Other": "Daily Life & Services",
    "Salons & Beauty": "Hair & Beauty",
    "Gyms & Sports": "Sports & Activities",
    "Doctors": "Health & Insurance",
    "Dentists": "Health & Insurance",
    "Translators": "Documents & Bureaucracy",
    "Courses & Teachers": "Integration & Language",
    "Vets & Pets": "Pets & Animals",
    "Places & Outings": "Ski & Trekking",
}


# ── Kinds / Topics ───────────────────────────────────────────────────────────
def test_fourteen_kinds_each_with_their_fixed_topic():
    assert len(Kind) == 14
    for kind, topic in EXPECTED_TOPICS.items():
        assert topic_for_kind(kind).value == topic
        assert KIND_TOPIC[Kind(kind)].value == topic


def test_every_kind_topic_is_a_menu_category():
    menu = {c.en_name for c in _get_categories()}
    assert {t.value for t in KIND_TOPIC.values()} <= menu


# ── Config ───────────────────────────────────────────────────────────────────
def test_suggestions_config_defaults_match_yaml_for_api_and_ingestion():
    defaults = SuggestionsConfig()
    assert defaults.ranking_half_life_years == 2
    assert defaults.summary_size == 5
    assert (
        defaults.max_clusters,
        defaults.candidate_clusters,
        defaults.max_members,
    ) == (
        6,
        10,
        20,
    )
    assert defaults.collection_name != load_settings().vector_store.collection_name
    assert load_settings().suggestions == defaults
    assert load_ingestion_settings().suggestions == defaults


# ── Cluster entry format ─────────────────────────────────────────────────────
def test_cluster_entry_derives_topic_and_rejects_mismatch(seeded_clusters):
    assert seeded_clusters[1].topic.value == "Health & Insurance"
    data = seeded_clusters[1].model_dump(mode="json")
    data["topic"] = "Hair & Beauty"
    with pytest.raises(ValidationError):
        ClusterEntry(**data)


@pytest.mark.parametrize("field", ["author", "member_name", "phone"])
def test_cluster_entry_has_no_author_name_or_phone_field(seeded_clusters, field):
    data = seeded_clusters[0].model_dump(mode="json")
    with pytest.raises(ValidationError):
        ClusterEntry(**{**data, field: "x"})
    data["members"][0][field] = "x"
    with pytest.raises(ValidationError):
        ClusterEntry(**data)


# ── Loader ───────────────────────────────────────────────────────────────────
class _Embedders:
    """Records the texts it is asked to embed; deterministic tiny vectors."""

    def __init__(self):
        self.dense_texts: list[str] = []
        self.sparse_texts: list[str] = []

    def dense(self, texts):
        self.dense_texts += texts
        return [[1.0, 0.0, 0.0, float(len(t) % 5)] for t in texts]

    def sparse(self, texts):
        self.sparse_texts += texts
        return [
            qmodels.SparseVector(
                indices=[i % 100 for i in range(len(t.split()))],
                values=[1.0] * len(t.split()),
            )
            for t in texts
        ]


def _load(client, clusters, name="suggestions_test", emb=None):
    emb = emb or _Embedders()
    n = load_clusters(
        clusters, client, name, dense_embed=emb.dense, sparse_embed=emb.sparse
    )
    return n, emb


def test_loader_stores_one_point_per_cluster_with_expected_payload(seeded_clusters):
    client = QdrantClient(":memory:")
    n, _ = _load(client, seeded_clusters)
    points, _ = client.scroll("suggestions_test", limit=10, with_payload=True)
    assert n == len(points) == 3
    market = next(
        p.payload for p in points if p.payload["kind"] == "Markets & Groceries"
    )
    assert market["topic"] == "Food & Restaurants"
    assert market["label"] == "Produtos brasileiros"
    assert (market["thumbs_up"], market["thumbs_down"]) == (14, 1)
    assert market["last_date"] == "2026-05-20"
    assert [m["name"] for m in market["members"]] == [
        "Épicerie Tropical",
        "Grand Frais",
        "Sabor do Brasil",
    ]
    assert market["members"][2]["community_business"] is True
    assert market["summary"].startswith("Épicerie Tropical")


def test_embedded_text_covers_summary_all_items_and_all_names(seeded_clusters):
    client = QdrantClient(":memory:")
    _, emb = _load(client, seeded_clusters[:1])
    (dense_text,) = emb.dense_texts
    (sparse_text,) = emb.sparse_texts
    assert seeded_clusters[0].summary in dense_text
    for item in ("polvilho", "massa de pastel", "pão de queijo", "guaraná"):
        assert item in dense_text
    for item in ("polvilho", "massa de pastel", "pao de queijo"):
        assert item in sparse_text
    for name in ("epicerie tropical", "grand frais", "sabor do brasil"):
        assert name in sparse_text


def test_loader_never_writes_author_or_phone_data(seeded_clusters):
    client = QdrantClient(":memory:")
    _load(client, seeded_clusters)
    points, _ = client.scroll("suggestions_test", limit=10, with_payload=True)
    for p in points:
        assert not {"author", "authors", "phone", "member_name"} & set(p.payload)
        for m in p.payload["members"]:
            assert not {"author", "phone", "member_name"} & set(m)


def test_loading_suggestions_leaves_qa_collection_untouched(seeded_clusters):
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
            qmodels.PointStruct(
                id=1, vector={"dense": [1, 0, 0, 0]}, payload={"question": "q"}
            )
        ],
    )

    _load(client, seeded_clusters)
    _load(client, seeded_clusters)  # rebuild

    qa_points, _ = client.scroll("qa_kb", limit=10, with_payload=True)
    assert [(p.id, p.payload) for p in qa_points] == [(1, {"question": "q"})]


def test_rebuild_replaces_previous_suggestions_collection(seeded_clusters):
    client = QdrantClient(":memory:")
    _load(client, seeded_clusters)
    n, _ = _load(client, seeded_clusters[:1])
    points, _ = client.scroll("suggestions_test", limit=10)
    assert n == len(points) == 1
