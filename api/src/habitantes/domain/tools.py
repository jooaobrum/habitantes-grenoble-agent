"""Hybrid search tool — thin wrapper over Qdrant + sentence-transformers.

Contract:
  hybrid_search(query, categories, top_k)
    -> {"chunks": [...]}           on success
    -> {"error": {...}}            on failure

Strategy: dense (E5) + sparse (BM25 hashing) → RRF fusion → anchor rerank.
categories: up to 2 values filtered with OR logic (top-2 from classifier).

Clients are lazy-loaded on first use so that importing this module never
crashes in environments where Qdrant or the embedding model are unavailable.
"""

import hashlib
import logging
import re
from typing import Any

from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)

# ── Constants (must match ingestion pipeline) ─────────────────────────────────

_SPARSE_DIM = 262_144
_DENSE_VECTOR = "dense"
_SPARSE_VECTOR = "sparse"

_DENSE_PREFETCH_K = 80
_SPARSE_PREFETCH_K = 120
_FUSED_K = 30
_RERANK_TOP_K = 20
_ANCHOR_BONUS = 0.05

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ']+")

# ── Lazy client factories ─────────────────────────────────────────────────────

_dense_model = None
_qdrant_client = None
_collection_name: str | None = None


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


def _get_qdrant_client():
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient

        from habitantes.config import load_settings

        settings = load_settings()
        _qdrant_client = QdrantClient(url=settings.vector_store.qdrant_url)
    return _qdrant_client


# ── Sparse hashing (identical to ingestion pipeline) ─────────────────────────


def _sparse_hash_vector(text: str) -> qmodels.SparseVector:
    tokens = _TOKEN_RE.findall((text or "").lower())
    if not tokens:
        return qmodels.SparseVector(indices=[], values=[])

    counts: dict[int, int] = {}
    for tok in tokens:
        h = int.from_bytes(hashlib.md5(tok.encode()).digest(), "big") % _SPARSE_DIM
        counts[h] = counts.get(h, 0) + 1

    max_c = max(counts.values())
    items = sorted(counts.items())
    return qmodels.SparseVector(
        indices=[i for i, _ in items],
        values=[c / max_c for _, c in items],
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


# ── Category filter (OR logic for top-2) ─────────────────────────────────────


def _category_filter(categories: list[str] | None) -> qmodels.Filter | None:
    if not categories:
        return None
    conditions = [
        qmodels.FieldCondition(key="category", match=qmodels.MatchValue(value=cat))
        for cat in categories
    ]
    if len(conditions) == 1:
        return qmodels.Filter(must=conditions)
    return qmodels.Filter(should=conditions)  # OR across top-2 categories


# ── Anchor rerank (PT + FR stopwords) ────────────────────────────────────────

_PT_STOPWORDS = {
    "a",
    "o",
    "os",
    "as",
    "um",
    "uma",
    "uns",
    "umas",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "e",
    "ou",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "por",
    "para",
    "com",
    "sem",
    "que",
    "como",
    "onde",
    "quando",
    "qual",
    "quais",
    "quem",
    "porque",
    "pq",
    "pra",
    "pro",
    "isso",
    "essa",
    "esse",
    "aquele",
    "aquela",
    "aqui",
    "ali",
    "muito",
    "mais",
    "menos",
    "também",
    "tbm",
    "já",
    "não",
    "sim",
    "eu",
    "vc",
    "vcs",
    "vocês",
}
_FR_STOPWORDS = {
    "le",
    "la",
    "les",
    "un",
    "une",
    "des",
    "du",
    "de",
    "d",
    "et",
    "en",
    "à",
    "a",
    "au",
    "aux",
    "pour",
    "par",
    "sur",
    "dans",
    "avec",
    "sans",
    "ce",
    "cet",
    "cette",
    "ces",
    "qui",
    "que",
    "quoi",
    "dont",
    "où",
    "mais",
    "ou",
    "donc",
    "or",
    "ni",
    "ne",
    "pas",
    "plus",
    "moins",
    "très",
    "tres",
    "se",
    "sa",
    "son",
    "ses",
    "leur",
    "leurs",
    "mon",
    "ma",
    "mes",
    "ton",
    "ta",
    "tes",
    "nous",
    "vous",
    "ils",
    "elles",
    "je",
    "tu",
    "il",
    "elle",
    "on",
    "y",
    "lui",
    "leur",
}


def _extract_anchors(query: str, min_len: int = 4) -> list[str]:
    out, seen = [], set()
    for tok in _TOKEN_RE.findall(query):
        t = tok.lower()
        if len(t) < min_len or t in _PT_STOPWORDS or t in _FR_STOPWORDS or t in seen:
            continue
        out.append(t)
        seen.add(t)
    return out


def _rerank_with_anchors(query: str, points: list) -> list:
    anchors = _extract_anchors(query)
    if not anchors:
        return points

    head, tail = points[:_RERANK_TOP_K], points[_RERANK_TOP_K:]
    denom = max(1, len(anchors))

    rescored = []
    for sp in head:
        pl = sp.payload or {}
        blob = " ".join(
            str(pl.get(k) or "")
            for k in ("question", "answer", "category", "subcategory")
        ).lower()
        hits = sum(1 for a in anchors if a in blob)
        rescored.append((float(sp.score) + _ANCHOR_BONUS * (hits / denom), sp))

    rescored.sort(key=lambda x: x[0], reverse=True)
    return [sp for _, sp in rescored] + tail


# ── Public tool function ──────────────────────────────────────────────────────


def hybrid_search(
    query: str,
    categories: list[str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Hybrid search: dense + sparse (RRF) + anchor rerank.

    Args:
        query: User question (Portuguese/French mixed).
        categories: Up to 2 category labels for OR filter. None = no filter.
        top_k: Number of chunks to return.

    Returns:
        {"chunks": [{"text", "question", "answer", "source", "date",
                     "category", "score"}, ...]}
        or
        {"error": {"error_code", "message", "retryable"}}
    """
    collection = _get_collection_name()

    # 1. Build vectors
    try:
        q_dense = _embed_query(query)
    except Exception as exc:
        logger.error("Embedding failure: %s", exc)
        return {
            "error": {
                "error_code": "EMBEDDING_FAILURE",
                "message": str(exc),
                "retryable": False,
            }
        }

    q_sparse = _sparse_hash_vector(query)
    q_filter = _category_filter(categories)

    # 2. RRF fusion query (dense + sparse prefetch)
    try:
        client = _get_qdrant_client()
        res = client.query_points(
            collection_name=collection,
            prefetch=[
                qmodels.Prefetch(
                    query=q_sparse,
                    using=_SPARSE_VECTOR,
                    limit=_SPARSE_PREFETCH_K,
                    filter=q_filter,
                ),
                qmodels.Prefetch(
                    query=q_dense,
                    using=_DENSE_VECTOR,
                    limit=_DENSE_PREFETCH_K,
                    filter=q_filter,
                ),
            ],
            query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
            limit=_FUSED_K,
            with_payload=True,
            query_filter=q_filter,
        )
        points = list(res.points)
    except TimeoutError as exc:
        logger.error("Qdrant timeout: %s", exc)
        return {
            "error": {
                "error_code": "QDRANT_TIMEOUT",
                "message": str(exc),
                "retryable": True,
            }
        }
    except Exception as exc:
        logger.error("Qdrant unreachable: %s", exc)
        return {
            "error": {
                "error_code": "QDRANT_UNREACHABLE",
                "message": str(exc),
                "retryable": True,
            }
        }

    # 3. Anchor rerank
    reranked = _rerank_with_anchors(query, points)

    # 4. Map to contract format
    chunks = []
    for p in reranked[:top_k]:
        pl = p.payload or {}
        chunks.append(
            {
                "text": pl.get("answer", ""),
                "question": pl.get("question", ""),
                "answer": pl.get("answer", ""),
                "source": pl.get("subcategory") or str(pl.get("thread_id", "")),
                "thread_id": pl.get("thread_id"),
                "date": pl.get("thread_start", ""),
                "category": pl.get("category", ""),
                "score": float(p.score),
            }
        )

    return {"chunks": chunks}
