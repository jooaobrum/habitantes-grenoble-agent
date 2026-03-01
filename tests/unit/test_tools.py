"""Unit tests for domain/tools.py.

Qdrant client and the dense model are mocked so tests run without
any real service. Only the pure Python logic (hashing, rerank, mapping)
is exercised with real code.
"""

from unittest.mock import MagicMock

import pytest

import habitantes.domain.tools as tools_module
from habitantes.domain.tools import (
    _category_filter,
    _extract_anchors,
    _rerank_with_anchors,
    _sparse_hash_vector,
    hybrid_search,
)

# ── Shared fixture ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_collection_name(monkeypatch):
    """Always return a test collection name so no real settings are needed."""
    monkeypatch.setattr(tools_module, "_get_collection_name", lambda: "test_collection")
    monkeypatch.setattr(tools_module, "_collection_name", None)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_scored_point(
    score: float = 0.9,
    question: str = "Como renovar o titre de séjour?",
    answer: str = "Acesse o site da ANEF para renovar.",
    category: str = "Visa & Residency",
    subcategory: str = "Residence Permit",
    thread_start: str = "2024-05-01",
    thread_id: int = 42,
) -> MagicMock:
    point = MagicMock()
    point.score = score
    point.payload = {
        "question": question,
        "answer": answer,
        "category": category,
        "subcategory": subcategory,
        "thread_start": thread_start,
        "thread_id": thread_id,
    }
    return point


def _mock_qdrant(points: list) -> MagicMock:
    client = MagicMock()
    result = MagicMock()
    result.points = points
    client.query_points.return_value = result
    return client


def _mock_dense_model(dim: int = 4) -> MagicMock:
    import numpy as np

    model = MagicMock()
    model.encode.return_value = np.zeros((1, dim), dtype="float32")
    return model


# ── _sparse_hash_vector ───────────────────────────────────────────────────────


class TestSparseHashVector:
    def test_empty_text_returns_empty_vector(self):
        sv = _sparse_hash_vector("")
        assert sv.indices == []
        assert sv.values == []

    def test_returns_sparse_vector(self):
        sv = _sparse_hash_vector("renovar titre de séjour")
        assert len(sv.indices) > 0
        assert len(sv.values) == len(sv.indices)

    def test_values_normalized(self):
        sv = _sparse_hash_vector("visa visa visa residency")
        assert max(sv.values) == pytest.approx(1.0)

    def test_indices_sorted(self):
        sv = _sparse_hash_vector("banco CAF moradia")
        assert sv.indices == sorted(sv.indices)

    def test_deterministic(self):
        sv1 = _sparse_hash_vector("test query grenoble")
        sv2 = _sparse_hash_vector("test query grenoble")
        assert sv1.indices == sv2.indices
        assert sv1.values == sv2.values


# ── _category_filter ─────────────────────────────────────────────────────────


class TestCategoryFilter:
    def test_none_returns_none(self):
        assert _category_filter(None) is None

    def test_empty_list_returns_none(self):
        assert _category_filter([]) is None

    def test_single_category_uses_must(self):
        f = _category_filter(["Visa & Residency"])
        assert f is not None
        assert f.must is not None
        assert f.should is None

    def test_two_categories_uses_should(self):
        f = _category_filter(["Visa & Residency", "Housing & CAF"])
        assert f is not None
        assert f.should is not None
        assert len(f.should) == 2


# ── _extract_anchors ──────────────────────────────────────────────────────────


class TestExtractAnchors:
    def test_filters_stopwords(self):
        anchors = _extract_anchors("Como renovar visto grenoble")
        assert "como" not in anchors

    def test_filters_short_tokens(self):
        anchors = _extract_anchors("ir ao banco")
        assert "ao" not in anchors
        assert "ir" not in anchors

    def test_returns_unique(self):
        anchors = _extract_anchors("anef anef préfecture")
        assert anchors.count("anef") == 1

    def test_normalises_to_lowercase(self):
        anchors = _extract_anchors("ANEF Préfecture")
        assert all(a == a.lower() for a in anchors)


# ── _rerank_with_anchors ──────────────────────────────────────────────────────


class TestRerankWithAnchors:
    def test_no_anchors_preserves_order(self):
        points = [_make_scored_point(score=0.9), _make_scored_point(score=0.7)]
        result = _rerank_with_anchors("de e ou em", points)  # all stopwords
        assert result == points

    def test_anchor_hit_moves_point_up(self):
        low = _make_scored_point(score=0.5, answer="sem informação relevante")
        high = _make_scored_point(
            score=0.6, answer="Acesse o site da ANEF para renovar o titre"
        )
        result = _rerank_with_anchors("renovar titre ANEF", [low, high])
        # high has anchor hits → should end up first after rerank
        scores_after = [p.score for p in result]
        assert scores_after[0] >= scores_after[1]


# ── hybrid_search — happy path ────────────────────────────────────────────────


class TestHybridSearchSuccess:
    def test_returns_chunks_list(self, monkeypatch):
        points = [_make_scored_point(score=0.92), _make_scored_point(score=0.85)]
        monkeypatch.setattr(
            tools_module, "_get_qdrant_client", lambda: _mock_qdrant(points)
        )
        monkeypatch.setattr(
            tools_module, "_get_dense_model", lambda: _mock_dense_model()
        )
        monkeypatch.setattr(tools_module, "_qdrant_client", None)
        monkeypatch.setattr(tools_module, "_dense_model", None)

        result = hybrid_search(
            "Como renovar titre de séjour?", categories=["Visa & Residency"]
        )

        assert "chunks" in result
        assert len(result["chunks"]) == 2

    def test_chunk_has_required_fields(self, monkeypatch):
        monkeypatch.setattr(
            tools_module,
            "_get_qdrant_client",
            lambda: _mock_qdrant([_make_scored_point()]),
        )
        monkeypatch.setattr(
            tools_module, "_get_dense_model", lambda: _mock_dense_model()
        )
        monkeypatch.setattr(tools_module, "_qdrant_client", None)
        monkeypatch.setattr(tools_module, "_dense_model", None)

        result = hybrid_search("pergunta", categories=None)
        chunk = result["chunks"][0]

        for field in (
            "text",
            "question",
            "answer",
            "source",
            "date",
            "category",
            "score",
        ):
            assert field in chunk, f"Missing field: {field}"

    def test_chunk_score_is_float(self, monkeypatch):
        monkeypatch.setattr(
            tools_module,
            "_get_qdrant_client",
            lambda: _mock_qdrant([_make_scored_point(score=0.88)]),
        )
        monkeypatch.setattr(
            tools_module, "_get_dense_model", lambda: _mock_dense_model()
        )
        monkeypatch.setattr(tools_module, "_qdrant_client", None)
        monkeypatch.setattr(tools_module, "_dense_model", None)

        result = hybrid_search("test")
        assert isinstance(result["chunks"][0]["score"], float)

    def test_empty_qdrant_returns_empty_chunks(self, monkeypatch):
        monkeypatch.setattr(
            tools_module, "_get_qdrant_client", lambda: _mock_qdrant([])
        )
        monkeypatch.setattr(
            tools_module, "_get_dense_model", lambda: _mock_dense_model()
        )
        monkeypatch.setattr(tools_module, "_qdrant_client", None)
        monkeypatch.setattr(tools_module, "_dense_model", None)

        result = hybrid_search("sem resultados")
        assert result == {"chunks": []}

    def test_top_k_limits_results(self, monkeypatch):
        points = [_make_scored_point(score=1.0 - i * 0.1) for i in range(10)]
        monkeypatch.setattr(
            tools_module, "_get_qdrant_client", lambda: _mock_qdrant(points)
        )
        monkeypatch.setattr(
            tools_module, "_get_dense_model", lambda: _mock_dense_model()
        )
        monkeypatch.setattr(tools_module, "_qdrant_client", None)
        monkeypatch.setattr(tools_module, "_dense_model", None)

        result = hybrid_search("pergunta", top_k=3)
        assert len(result["chunks"]) == 3

    def test_no_category_filter(self, monkeypatch):
        monkeypatch.setattr(
            tools_module,
            "_get_qdrant_client",
            lambda: _mock_qdrant([_make_scored_point()]),
        )
        monkeypatch.setattr(
            tools_module, "_get_dense_model", lambda: _mock_dense_model()
        )
        monkeypatch.setattr(tools_module, "_qdrant_client", None)
        monkeypatch.setattr(tools_module, "_dense_model", None)

        result = hybrid_search("qualquer pergunta", categories=None)
        assert "chunks" in result

    def test_two_categories_or_filter(self, monkeypatch):
        monkeypatch.setattr(
            tools_module,
            "_get_qdrant_client",
            lambda: _mock_qdrant([_make_scored_point()]),
        )
        monkeypatch.setattr(
            tools_module, "_get_dense_model", lambda: _mock_dense_model()
        )
        monkeypatch.setattr(tools_module, "_qdrant_client", None)
        monkeypatch.setattr(tools_module, "_dense_model", None)

        result = hybrid_search("test", categories=["Visa & Residency", "Housing & CAF"])
        assert "chunks" in result


# ── hybrid_search — error paths ───────────────────────────────────────────────


class TestHybridSearchErrors:
    def test_embedding_failure_returns_error(self, monkeypatch):
        def _bad_embed(_query):
            raise RuntimeError("model not loaded")

        monkeypatch.setattr(tools_module, "_embed_query", _bad_embed)

        result = hybrid_search("test")
        assert "error" in result
        assert result["error"]["error_code"] == "EMBEDDING_FAILURE"
        assert result["error"]["retryable"] is False

    def test_qdrant_timeout_returns_error(self, monkeypatch):
        def _bad_client():
            client = MagicMock()
            client.query_points.side_effect = TimeoutError("timed out")
            return client

        monkeypatch.setattr(tools_module, "_get_qdrant_client", _bad_client)
        monkeypatch.setattr(
            tools_module, "_get_dense_model", lambda: _mock_dense_model()
        )
        monkeypatch.setattr(tools_module, "_qdrant_client", None)
        monkeypatch.setattr(tools_module, "_dense_model", None)

        result = hybrid_search("test")
        assert result["error"]["error_code"] == "QDRANT_TIMEOUT"
        assert result["error"]["retryable"] is True

    def test_qdrant_unreachable_returns_error(self, monkeypatch):
        def _bad_client():
            client = MagicMock()
            client.query_points.side_effect = ConnectionError("refused")
            return client

        monkeypatch.setattr(tools_module, "_get_qdrant_client", _bad_client)
        monkeypatch.setattr(
            tools_module, "_get_dense_model", lambda: _mock_dense_model()
        )
        monkeypatch.setattr(tools_module, "_qdrant_client", None)
        monkeypatch.setattr(tools_module, "_dense_model", None)

        result = hybrid_search("test")
        assert result["error"]["error_code"] == "QDRANT_UNREACHABLE"
        assert result["error"]["retryable"] is True
