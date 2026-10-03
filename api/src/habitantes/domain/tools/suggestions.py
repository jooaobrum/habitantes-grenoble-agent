"""search_suggestions: query the Suggestions collection (one point per Cluster).

Hybrid search: a dense branch with its own relevance floor
(`settings.suggestions.min_relevance`, independent of the Q&A gate) and a sparse
(BM25 keyword) branch so an item name ("polvilho") finds the place that sells it;
the two are fused with RRF. Returns up to `max_clusters` Clusters, each with its
top members; an explicit `no_results` signal when nothing matches.
"""

import logging
import math
import re
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


def _br_date(value: Any) -> str:
    """ISO date (yyyy-mm-dd) -> dd/mm/aaaa, the format the answer shows."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(value))
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else str(value)


def format_member_line(m: dict) -> str:
    """One member as an answer-ready list item (also used by the agent to render)."""
    flag = f" {COMMUNITY_BUSINESS_LABEL}" if m.get("community_business") else ""
    items = ", ".join(_clip(i) for i in m.get("items", [])[:_MAX_ITEMS])
    return (
        f"- **{_clip(m['name'])}**{flag} — {m['thumbs_up']}👍/{m['thumbs_down']}👎 · "
        f"última menção {_br_date(m['last_date'])} — indicado para: "
        f"{items or 'não especificado'}"
    )


def _format_cluster(cluster: dict, members: list[dict]) -> str:
    """One Cluster as text. Member lines are already in the final answer shape, so
    the model copies a line (picking the relevant ones) instead of composing one."""
    lines = [
        f"Grupo: {_clip(cluster['label'])} (tipo: {cluster['kind']}) | "
        f"{cluster['thumbs_up']}👍/{cluster['thumbs_down']}👎 no grupo | "
        f"última menção: {_br_date(cluster['last_date'])}"
    ]
    lines.extend(format_member_line(m) for m in members)
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

    pool = cfg.candidate_clusters
    kinds = [kind_value] if kind_value else infer_kinds(query)
    # Unfiltered lists plus, for an inferred Kind, Kind-filtered ones: the query
    # naming a category ("dentista") should surface that Kind's Clusters even when
    # item-heavy Clusters of other Kinds score higher.
    filters = [q_filter] if kind_value else [None] + [_kind_filter(k) for k in kinds]
    try:
        client = _search._get_qdrant_client()
        ranked_lists: list[list[Any]] = []
        for flt in filters:
            # Dense branch keeps the semantic floor; the sparse branch is keyword
            # evidence (any BM25 match) and needs no cosine threshold.
            ranked_lists.append(
                [
                    p
                    for p in client.query_points(
                        collection_name=_collection_name(),
                        query=q_dense,
                        using=_DENSE_VECTOR,
                        limit=pool,
                        query_filter=flt,
                        score_threshold=cfg.min_relevance,
                        with_payload=True,
                    ).points
                    if float(p.score) >= cfg.min_relevance
                ]
            )
            if q_sparse is not None:
                ranked_lists.append(
                    client.query_points(
                        collection_name=_collection_name(),
                        query=q_sparse,
                        using=_SPARSE_VECTOR,
                        limit=pool,
                        query_filter=flt,
                        with_payload=True,
                    ).points
                )
    except Exception as exc:
        code = _search._classify_qdrant_error(exc)
        logger.error("Qdrant %s: %s", code, exc)
        return {"error": {"error_code": code, "message": str(exc), "retryable": True}}

    fused: dict[str, float] = {}
    by_id: dict[str, Any] = {}
    for pts in ranked_lists:
        for rank, p in enumerate(pts):
            pid = str(p.id)
            fused[pid] = fused.get(pid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            by_id.setdefault(pid, p)

    candidates = []
    for pid in sorted(fused, key=lambda x: fused[x], reverse=True):
        payload = dict(by_id[pid].payload or {})
        if not any(_net(m) > 0 for m in payload.get("members", [])):
            continue
        payload["score"] = fused[pid]
        candidates.append(payload)

    clusters, more = _merge_members(candidates, query, cfg)
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


def _kind_filter(kind: str) -> qmodels.Filter:
    return qmodels.Filter(
        must=[qmodels.FieldCondition(key="kind", match=qmodels.MatchValue(value=kind))]
    )


def _norm_key(name: str) -> str:
    return " ".join(strip_accents(name).lower().split())


def _merge_members(
    candidates: list[dict], query: str, cfg: Any
) -> tuple[list[dict], bool]:
    """Member-level merge over the candidate Clusters (best first).

    The same business is often split across several Clusters, so members are
    deduped by name and their votes and Cluster scores pooled: a member named in
    several relevant Clusters outranks one named in a single Cluster. Ranking is
    pooled Cluster score weighted by log net votes; the top `max_members` are shown, each
    under the best Cluster that contains it. Returns (clusters, more).
    """
    words = set(strip_accents(query).lower().split()) - _STOPWORDS
    pooled: dict[str, dict] = {}
    for rank, payload in enumerate(candidates):
        for m in payload.get("members", []):
            key = _norm_key(m.get("name", ""))
            e = pooled.get(key)
            if e is None:
                e = pooled[key] = {
                    "member": dict(m),
                    "score": 0.0,
                    "home": payload,
                    "match": bool(
                        words
                        & (
                            _tokens(m.get("name", ""))
                            | {w for i in m.get("items", []) for w in _tokens(i)}
                        )
                    ),
                }
            else:
                mm = e["member"]
                mm["thumbs_up"] = int(mm["thumbs_up"]) + int(m.get("thumbs_up", 0))
                mm["thumbs_down"] = int(mm["thumbs_down"]) + int(
                    m.get("thumbs_down", 0)
                )
                mm["last_date"] = max(mm.get("last_date", ""), m.get("last_date", ""))
                mm["items"] = list(
                    dict.fromkeys([*mm.get("items", []), *m.get("items", [])])
                )
            e["score"] += 1.0 / (rank + 1)
    ranked = sorted(
        (e for e in pooled.values() if _net(e["member"]) > 0),
        key=lambda e: (
            e["score"] * math.log2(2 + _net(e["member"])),
            e["member"].get("last_date", ""),
        ),
        reverse=True,
    )
    top = ranked[: cfg.max_members]
    out: list[dict] = []
    homes: dict[int, dict] = {}
    for e in top:
        home = e["home"]
        if id(home) not in homes:
            if len(homes) >= cfg.max_clusters:
                continue
            homes[id(home)] = home
            home["all_members"] = home.get("members", [])
            home["members"] = []
            out.append(home)
        home["members"].append(e["member"])
    for home in out:
        home["hidden_count"] = max(0, len(home["all_members"]) - len(home["members"]))
    shown_n = sum(len(c["members"]) for c in out)
    return out, len(ranked) > shown_n


def infer_kinds(query: str) -> list[str]:
    """Kinds whose Portuguese keywords appear in the query (words unique to one Kind)."""
    from habitantes.domain.suggestions import KIND_KEYWORDS_PT

    text = " " + strip_accents(query).lower() + " "
    owners: dict[str, set[str]] = {}
    for k, words in KIND_KEYWORDS_PT.items():
        for w in words:
            owners.setdefault(strip_accents(w).lower(), set()).add(k.value)
    found: list[str] = []
    for w, ks in owners.items():
        if len(ks) == 1 and re.search(rf"\b{re.escape(w)}(s|es)?\b", text):
            found.extend(k for k in ks if k not in found)
    return found


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
