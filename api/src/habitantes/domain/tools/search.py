import logging
from typing import Any
from ._embedding import _embed_query, _embed_sparse_query, _DENSE_VECTOR, _SPARSE_VECTOR
from ._ranking import (
    _calculate_date_decay,
    _category_filter,
    strip_accents,
    enrich_bm25_input,
    _rerank_with_anchors,
    _deduplicate_by_thread,
)

logger = logging.getLogger(__name__)

_qdrant_client = None
_collection_name = None


def _get_collection_name() -> str:
    from habitantes.config import load_settings

    return load_settings().vector_store.collection_name


def _get_qdrant_client():
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient
        from habitantes.config import load_settings

        settings = load_settings()
        _qdrant_client = QdrantClient(url=settings.vector_store.qdrant_url)
    return _qdrant_client


# ── Public tool function ──────────────────────────────────────────────────────


def hybrid_search(
    query: str,
    categories: list[str] | None = None,
    top_k: int | None = None,
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
    from habitantes.config import load_settings

    settings = load_settings()
    collection = _get_collection_name()

    if top_k is None:
        top_k = settings.search.top_k

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

    try:
        query_norm = strip_accents(query)
        q_sparse = _embed_sparse_query(
            enrich_bm25_input(query_norm)
        )  # normalize -> enrich
    except Exception as exc:
        logger.error("Sparse embedding failure: %s", exc)
        return {
            "error": {
                "error_code": "SPARSE_EMBEDDING_FAILURE",
                "message": str(exc),
                "retryable": False,
            }
        }

    q_filter = _category_filter(categories)

    # 2. Weighted Fusion (0.7 Dense + 0.3 Sparse)
    try:
        client = _get_qdrant_client()

        # Fetch dense results
        dense_prefetch = client.query_points(
            collection_name=collection,
            query=q_dense,
            using=_DENSE_VECTOR,
            limit=settings.search.dense_prefetch_k,
            query_filter=q_filter,
            with_payload=True,
        ).points

        # Fetch sparse results
        sparse_prefetch = client.query_points(
            collection_name=collection,
            query=q_sparse,
            using=_SPARSE_VECTOR,
            limit=settings.search.sparse_prefetch_k,
            query_filter=q_filter,
            with_payload=True,
        ).points

        # RRF-style weighted combination: 0.7 dense / 0.3 sparse
        # Score = w_dense * (1/(k + rank_dense)) + w_sparse * (1/(k + rank_sparse))
        W_DENSE = settings.search.w_dense
        W_SPARSE = settings.search.w_sparse
        RRF_K = settings.search.rrf_k

        scores: dict[str, float] = {}
        points_map: dict[str, Any] = {}

        for i, p in enumerate(dense_prefetch):
            pid = str(p.id)
            date_str = p.payload.get("date") if p.payload else None
            decay = _calculate_date_decay(date_str)
            scores[pid] = scores.get(pid, 0) + W_DENSE * (1.0 / (RRF_K + i + 1)) * decay
            points_map[pid] = p

        for i, p in enumerate(sparse_prefetch):
            pid = str(p.id)
            date_str = p.payload.get("date") if p.payload else None
            decay = _calculate_date_decay(date_str)
            scores[pid] = (
                scores.get(pid, 0) + W_SPARSE * (1.0 / (RRF_K + i + 1)) * decay
            )
            points_map[pid] = p

        # Sort by merged RR score and keep top _FUSED_K
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        points = [points_map[pid] for pid in sorted_ids[: settings.search.fused_k]]

        # Use the merged RR score as point score for later reranking
        for p in points:
            p.score = scores[str(p.id)]

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

    # 4. Thread-level deduplication — keep best chunk per thread
    unique = _deduplicate_by_thread(reranked)

    # 5. Map to contract format
    chunks = []
    for p in unique[:top_k]:
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


def list_subcategories() -> list[str]:
    """Fetch unique subcategories from the vector store."""
    client = _get_qdrant_client()
    collection = _get_collection_name()
    try:
        # Use scroll with a reasonable limit to find unique subcategories in the payload
        # This keeps it simple and compatible across versions
        points, _ = client.scroll(
            collection_name=collection,
            with_payload=["subcategory"],
            limit=1000,
        )
        subs = set()
        for p in points:
            if p.payload and p.payload.get("subcategory"):
                subs.add(p.payload["subcategory"])
        return sorted(list(subs))
    except Exception as exc:
        logger.error("Failed to list subcategories: %s", exc)
        return []


def get_category_chunks(category: str, limit: int = 15) -> list[dict]:
    """Fetch recent chunks from a specific category or subcategory."""
    client = _get_qdrant_client()
    collection = _get_collection_name()
    try:
        # We try to match either main category or subcategory
        from qdrant_client.http import models as qmodels

        q_filter = qmodels.Filter(
            should=[
                qmodels.FieldCondition(
                    key="category", match=qmodels.MatchValue(value=category)
                ),
                qmodels.FieldCondition(
                    key="subcategory", match=qmodels.MatchValue(value=category)
                ),
            ]
        )

        points, _ = client.scroll(
            collection_name=collection,
            scroll_filter=q_filter,
            limit=limit,
            with_payload=True,
        )

        chunks = []
        for p in points:
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
                }
            )
        return chunks
    except Exception as exc:
        logger.error("Failed to fetch category chunks: %s", exc)
        return []


# ── LangChain tool wrapper (for ReAct agent) ─────────────────────────────────


def _make_search_tool():
    """Create a LangChain tool wrapping hybrid_search for use with bind_tools."""
    from langchain_core.tools import tool

    @tool
    def search_knowledge_base(query: str, category: str = "") -> Any:
        """Search the knowledge base of Brazilian expats in Grenoble.

        Use this tool to find information about life in Grenoble for Brazilian
        expats. Topics include visas, housing, healthcare, banking, transport,
        university, food, safety, and more.

        Args:
            query: The search query in Portuguese or French.
            category: Optional category filter (e.g. "Visa & Residency",
                      "Banking & Finance"). Leave empty to search all categories.
        """
        from habitantes.config import load_settings

        settings = load_settings()
        cats = [category] if category else None
        result = hybrid_search(
            query=query, categories=cats, top_k=settings.search.top_k
        )

        if "error" in result:
            return f"Erro na busca: {result['error']['message']}"

        chunks = result.get("chunks", [])
        if not chunks:
            return "Nenhum resultado encontrado na base de conhecimento."

        parts = []
        for i, chunk in enumerate(chunks, 1):
            cat = chunk.get("category", "geral")
            date = chunk.get("date", "data desconhecida")
            text = chunk.get("text") or chunk.get("answer", "")
            parts.append(f"[{i}] Categoria: {cat} | Data: {date}\n{text}")

        return {
            "formatted": "\n\n".join(parts),
            "chunks": chunks,
        }

    return search_knowledge_base


def _make_list_subcategories_tool():
    from langchain_core.tools import tool

    @tool
    def list_knowledge_subcategories() -> str:
        """Get a list of all specific subcategories available in the knowledge base.
        Use this when standard search fails or you need to see what specific topics exist.
        """
        subs = list_subcategories()
        if not subs:
            return "Nenhuma subcategoria encontrada."
        return "Subcategorias disponíveis:\n" + "\n".join(f"- {s}" for s in subs)

    return list_knowledge_subcategories


def _make_get_category_chunks_tool():
    from langchain_core.tools import tool

    @tool
    def get_chunks_by_category(category: str) -> str:
        """Fetch several recent information chunks from a specific category or subcategory.
        Use this for a 'deep dive' when you know a relevant subcategory but search results were weak.

        Args:
            category: The name of the category or subcategory to explore.
        """
        chunks = get_category_chunks(category)
        if not chunks:
            return f"Nenhum resultado encontrado para a categoria '{category}'."

        parts = []
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get("text") or chunk.get("answer", "")
            parts.append(f"[{i}] {text}")

        return "\n\n".join(parts)

    return get_chunks_by_category


# Lazy singletons
_search_tool = None
_list_subs_tool = None
_get_cat_chunks_tool = None


def get_search_tool():
    """Return the LangChain tool for search_knowledge_base (singleton)."""
    global _search_tool
    if _search_tool is None:
        _search_tool = _make_search_tool()
    return _search_tool


def get_list_subcategories_tool():
    global _list_subs_tool
    if _list_subs_tool is None:
        _list_subs_tool = _make_list_subcategories_tool()
    return _list_subs_tool


def get_get_category_chunks_tool():
    global _get_cat_chunks_tool
    if _get_cat_chunks_tool is None:
        _get_cat_chunks_tool = _make_get_category_chunks_tool()
    return _get_cat_chunks_tool
