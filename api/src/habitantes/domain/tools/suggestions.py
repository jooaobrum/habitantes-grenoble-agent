"""search_suggestions: query the Suggestions collection (one point per Cluster).

Dense search with its own relevance threshold (`settings.suggestions.min_relevance`,
independent of the Q&A gate). Returns up to `max_clusters` Clusters, each with its
top members; an explicit `no_results` signal when nothing clears the threshold.
"""

import logging
from typing import Any

from qdrant_client.http import models as qmodels

from . import search as _search
from ._embedding import _DENSE_VECTOR, _embed_query
from ._ranking import strip_accents

logger = logging.getLogger(__name__)

NO_RESULTS_MESSAGE = (
    "Nenhuma sugestão da comunidade encontrada para este pedido. Diga isso ao "
    "usuário e complemente com web_search_grenoble, deixando claro que vem da web."
)


def _collection_name() -> str:
    from habitantes.config import load_settings

    return load_settings().suggestions.collection_name


def _parse_kind(kind: str) -> str | None:
    """Match a free-text Kind to its canonical value (case/accent-insensitive)."""
    from habitantes.domain.suggestions import Kind

    wanted = strip_accents(kind or "").strip().lower()
    for k in Kind:
        if strip_accents(k.value).lower() == wanted:
            return k.value
    return None


def _net(member: dict) -> int:
    return int(member.get("thumbs_up", 0)) - int(member.get("thumbs_down", 0))


def _select_members(
    members: list[dict], query: str, summary_size: int, max_extra: int
) -> list[dict]:
    """Top members by net votes (disliked ones dropped), plus a few long-tail
    members whose Items match the query — a place named once for a specific item."""
    ranked = sorted(
        (m for m in members if _net(m) > 0),
        key=lambda m: (_net(m), m.get("last_date", "")),
        reverse=True,
    )
    top, rest = ranked[:summary_size], ranked[summary_size:]
    words = {w for w in strip_accents(query).lower().split() if len(w) > 3}
    extras = [
        m
        for m in rest
        if words
        & {w for i in m.get("items", []) for w in strip_accents(i).lower().split()}
    ]
    return top + extras[:max_extra]


def _format_cluster(cluster: dict, members: list[dict]) -> str:
    lines = [
        f"Grupo: {cluster['label']} (tipo: {cluster['kind']}) | "
        f"{cluster['thumbs_up']}👍/{cluster['thumbs_down']}👎 no grupo | "
        f"última menção: {cluster['last_date']}"
    ]
    for m in members:
        flag = (
            " [negócio de membro da comunidade]" if m.get("community_business") else ""
        )
        items = ", ".join(m.get("items", [])) or "não especificado"
        lines.append(
            f"- {m['name']}{flag}: {m['thumbs_up']}👍/{m['thumbs_down']}👎 | "
            f"última menção: {m['last_date']} | indicado para: {items}"
        )
    return "\n".join(lines)


def search_clusters(query: str, kind: str = "") -> dict[str, Any]:
    """Return {"clusters": [...], "formatted": str, "top_score": float},
    {"no_results": True, "formatted": str}, or {"error": {...}}."""
    from habitantes.config import load_settings

    cfg = load_settings().suggestions

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

    kind_value = _parse_kind(kind) if kind else None
    q_filter = (
        qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="kind", match=qmodels.MatchValue(value=kind_value)
                )
            ]
        )
        if kind_value
        else None
    )

    try:
        points = (
            _search._get_qdrant_client()
            .query_points(
                collection_name=_collection_name(),
                query=q_dense,
                using=_DENSE_VECTOR,
                limit=cfg.max_clusters,
                query_filter=q_filter,
                score_threshold=cfg.min_relevance,
                with_payload=True,
            )
            .points
        )
    except Exception as exc:
        code = _search._classify_qdrant_error(exc)
        logger.error("Qdrant %s: %s", code, exc)
        return {"error": {"error_code": code, "message": str(exc), "retryable": True}}

    hits = [p for p in points if float(p.score) >= cfg.min_relevance]
    hits = hits[: cfg.max_clusters]
    clusters = []
    for p in hits:
        payload = dict(p.payload or {})
        payload["members"] = _select_members(
            payload.get("members", []), query, cfg.summary_size, cfg.max_extra_members
        )
        payload["score"] = float(p.score)
        clusters.append(payload)
    clusters = [c for c in clusters if c["members"]]

    if not clusters:
        return {"no_results": True, "formatted": NO_RESULTS_MESSAGE}
    return {
        "clusters": clusters,
        "formatted": "\n\n".join(_format_cluster(c, c["members"]) for c in clusters),
        "top_score": max(c["score"] for c in clusters),
    }


def _make_search_suggestions_tool():
    from langchain_core.tools import tool

    @tool
    def search_suggestions(query: str, kind: str = "") -> Any:
        """Search what the community recommends: businesses, places and products
        (dentists, hairdressers, markets, shops, translators, restaurants...).

        Use for "who/where do you recommend for X?" requests.

        Args:
            query: What the user needs, in natural language (Portuguese), e.g.
                   "onde compro massa de pastel" or "dentista".
            kind: Optional Kind filter: Restaurants & Bars, Markets & Groceries,
                  Shops, Products, Salons & Beauty, Gyms & Sports, Doctors,
                  Dentists, Translators, Professional Services, Courses &
                  Teachers, Vets & Pets, Places & Outings, Other. Leave empty
                  when unsure.
        """
        return search_clusters(query, kind)

    return search_suggestions


_suggestions_tool = None


def get_suggestions_tool():
    """Return the LangChain tool for search_suggestions (singleton)."""
    global _suggestions_tool
    if _suggestions_tool is None:
        _suggestions_tool = _make_search_suggestions_tool()
    return _suggestions_tool
