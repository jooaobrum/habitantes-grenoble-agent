"""search_suggestions: query the Suggestions collection (one point per Cluster).

Hybrid search: a dense branch with its own relevance floor
(`settings.suggestions.min_relevance`, independent of the Q&A gate) and a sparse
(BM25 keyword) branch so an item name ("polvilho") finds the place that sells it;
the two are fused with RRF. Returns up to `max_clusters` Clusters, each with its
top members; an explicit `no_results` signal when nothing matches.
"""

import logging
from typing import Any

from qdrant_client.http import models as qmodels

from . import search as _search
from ._embedding import _DENSE_VECTOR, _SPARSE_VECTOR, _embed_query, _embed_sparse_query
from ._ranking import _FR_STOPWORDS, _PT_STOPWORDS, enrich_bm25_input, strip_accents

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


_MAX_ITEMS = 3
_MAX_TEXT = 80
COMMUNITY_BUSINESS_LABEL = "[negócio de membro do grupo — divulgação própria]"
AVAILABILITY_REMINDER = (
    "Lembrete: avise o usuário para confirmar disponibilidade/horários. "
    "São indicações da comunidade, não uma lista exaustiva."
)
MORE_SUGGESTIONS_NOTE = (
    "Há mais sugestões da comunidade do que as mostradas; diga isso ao usuário."
)


def _clip(text: str, n: int = _MAX_TEXT) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


_RRF_K = 60
_STOPWORDS = {strip_accents(w).lower() for w in _PT_STOPWORDS | _FR_STOPWORDS}


def _tokens(text: str) -> set[str]:
    return set(strip_accents(text).lower().split())


def _select_members(
    members: list[dict], query: str, summary_size: int, max_extra: int
) -> tuple[list[dict], int]:
    """Top members by net votes (score <= 0 dropped), plus up to `max_extra`
    long-tail members whose name or Items match the query. Returns the shown
    members and how many eligible members remain unshown ("+K outras")."""
    ranked = sorted(
        (m for m in members if _net(m) > 0),
        key=lambda m: (_net(m), m.get("last_date", "")),
        reverse=True,
    )
    top, rest = ranked[:summary_size], ranked[summary_size:]
    words = set(strip_accents(query).lower().split()) - _STOPWORDS
    extras = [
        m
        for m in rest
        if words
        & (
            _tokens(m.get("name", ""))
            | {w for i in m.get("items", []) for w in _tokens(i)}
        )
    ][:max_extra]
    return top + extras, len(rest) - len(extras)


def _format_cluster(cluster: dict, members: list[dict]) -> str:
    lines = [
        f"Grupo: {_clip(cluster['label'])} (tipo: {cluster['kind']}) | "
        f"{cluster['thumbs_up']}👍/{cluster['thumbs_down']}👎 no grupo | "
        f"última menção: {cluster['last_date']}"
    ]
    for m in members:
        flag = f" {COMMUNITY_BUSINESS_LABEL}" if m.get("community_business") else ""
        items = ", ".join(_clip(i) for i in m.get("items", [])[:_MAX_ITEMS])
        lines.append(
            f"- {_clip(m['name'])}{flag}: {m['thumbs_up']}👍/{m['thumbs_down']}👎 | "
            f"última menção: {m['last_date']} | indicado para: "
            f"{items or 'não especificado'}"
        )
    hidden = cluster.get("hidden_count", 0)
    if hidden:
        lines.append(f"+{hidden} outras")
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
        q_sparse = _embed_sparse_query(enrich_bm25_input(strip_accents(query)))
    except Exception as exc:  # keyword branch is optional: fail open to dense only
        logger.warning("Sparse embedding failure, dense only: %s", exc)
        q_sparse = None

    limit = cfg.max_clusters + 1  # one extra detects 'there are more'
    try:
        client = _search._get_qdrant_client()
        # Dense branch keeps the semantic floor; the sparse branch is keyword
        # evidence (any BM25 match) and needs no cosine threshold.
        dense_pts = client.query_points(
            collection_name=_collection_name(),
            query=q_dense,
            using=_DENSE_VECTOR,
            limit=limit,
            query_filter=q_filter,
            score_threshold=cfg.min_relevance,
            with_payload=True,
        ).points
        sparse_pts = (
            client.query_points(
                collection_name=_collection_name(),
                query=q_sparse,
                using=_SPARSE_VECTOR,
                limit=limit,
                query_filter=q_filter,
                with_payload=True,
            ).points
            if q_sparse is not None
            else []
        )
    except Exception as exc:
        code = _search._classify_qdrant_error(exc)
        logger.error("Qdrant %s: %s", code, exc)
        return {"error": {"error_code": code, "message": str(exc), "retryable": True}}

    fused: dict[str, float] = {}
    dense_score: dict[str, float] = {}
    by_id: dict[str, Any] = {}
    for rank, p in enumerate(dense_pts):
        pid = str(p.id)
        if float(p.score) < cfg.min_relevance:
            continue
        dense_score[pid] = float(p.score)
        fused[pid] = fused.get(pid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        by_id[pid] = p
    for rank, p in enumerate(sparse_pts):
        pid = str(p.id)
        fused[pid] = fused.get(pid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        by_id.setdefault(pid, p)

    candidates = []
    for pid in sorted(fused, key=lambda x: fused[x], reverse=True):
        payload = dict(by_id[pid].payload or {})
        if not any(_net(m) > 0 for m in payload.get("members", [])):
            continue
        payload["score"] = fused[pid]
        payload["dense_score"] = dense_score.get(pid, 0.0)
        candidates.append(payload)
    more = len(candidates) > cfg.max_clusters
    clusters = candidates[: cfg.max_clusters]

    # PRD: the long-tail extras budget is global across the returned Clusters.
    extras_left = cfg.max_extra_members
    for payload in clusters:
        all_members = payload.get("members", [])
        shown, payload["hidden_count"] = _select_members(
            all_members, query, cfg.summary_size, extras_left
        )
        payload["members"] = shown
        n_top = min(cfg.summary_size, sum(1 for m in all_members if _net(m) > 0))
        extras_left -= len(shown) - n_top

    if not clusters:
        return {"no_results": True, "formatted": NO_RESULTS_MESSAGE}
    return {
        "clusters": clusters,
        "formatted": "\n\n".join(_format_cluster(c, c["members"]) for c in clusters)
        + "\n\n"
        + (MORE_SUGGESTIONS_NOTE + "\n" if more else "")
        + AVAILABILITY_REMINDER,
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
