import logging
from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)

_SPARSE_DIM = 262_144
_DENSE_VECTOR = "dense"
_SPARSE_VECTOR = "sparse"
_SPARSE_MODEL = "Qdrant/bm25"

_openai_client = None
_sparse_model = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI

        from habitantes.config import load_settings

        settings = load_settings()
        _openai_client = OpenAI(api_key=settings.llm.openai_api_key)
    return _openai_client


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Dense-embed a batch of texts with OpenAI. Vectors are L2-normalized."""
    from habitantes.config import load_settings

    client = _get_openai_client()
    model = load_settings().llm.embedding_model_name
    resp = client.embeddings.create(model=model, input=texts)
    return [d.embedding for d in resp.data]


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


# ── Dense embedding (query side) ──────────────────────────────────────────────


def _embed_query(query: str) -> list[float]:
    return _embed_texts([query])[0]
