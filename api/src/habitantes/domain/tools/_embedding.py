import logging
from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)

_SPARSE_DIM = 262_144
_DENSE_VECTOR = "dense"
_SPARSE_VECTOR = "sparse"
_SPARSE_MODEL = "Qdrant/bm25"

_dense_model = None
_sparse_model = None


def _get_collection_name() -> str:
    global _collection_name
    if _collection_name is None:
        from habitantes.config import load_settings

        _collection_name = load_settings().vector_store.collection_name
    return _collection_name


def _get_dense_model():
    global _dense_model
    if _dense_model is None:
        from sentence_transformers import SentenceTransformer

        from habitantes.config import load_settings

        settings = load_settings()
        _dense_model = SentenceTransformer(
            settings.llm.embedding_model_name,
            cache_folder=None,
        )
    return _dense_model


def _get_sparse_model():
    global _sparse_model
    if _sparse_model is None:
        from fastembed import SparseTextEmbedding

        _sparse_model = SparseTextEmbedding(model_name=_SPARSE_MODEL)
    return _sparse_model


# ── Sparse hashing (identical to ingestion pipeline) ─────────────────────────


def _embed_sparse_query(query: str) -> qmodels.SparseVector:
    model = _get_sparse_model()
    # model.embed returns a generator of SparseEmbedding
    sv = list(model.embed([query]))[0]
    return qmodels.SparseVector(
        indices=sv.indices.tolist(),
        values=sv.values.tolist(),
    )


# ── Dense embedding (query side — E5 convention) ──────────────────────────────


def _embed_query(query: str) -> list[float]:
    model = _get_dense_model()
    vec = model.encode(
        [f"query: {query}"],
        show_progress_bar=False,
        normalize_embeddings=True,
    )[0]
    return vec.tolist()  # type: ignore[return-value]
