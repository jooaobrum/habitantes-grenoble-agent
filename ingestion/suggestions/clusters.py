"""Suggestions -> Cluster entries: grouping seam, ranking, label + summary.

`cluster_mentions` groups Mentions by similarity; member lines, ranking and
summary work per group.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

import httpx
import numpy as np

from habitantes.domain.suggestions import ClusterEntry, ClusterMember, Kind
from ingestion.suggestions.extract import Mention
from ingestion.suggestions.llm import chat_json
from ingestion.suggestions.merge import normalise_name
from ingestion.suggestions.suggestions import Suggestion

logger = logging.getLogger(__name__)


MIN_MENTIONS_TO_SPLIT = 4  # fewer Mentions than this always form one Cluster


def _mention_text(m: Mention) -> str:
    return " ".join([*m.items, m.context or ""]).strip() or m.name


def cluster_mentions(
    kind: Kind,
    mentions: List[Mention],
    embed: Optional[Callable[[List[str]], List[List[float]]]] = None,
    cutoff: float = 0.75,
) -> List[List[Mention]]:
    """Group the counted Mentions of one Kind by similarity of Items + Context.

    Greedy leader clustering on cosine similarity: a Mention joins the Cluster whose
    centroid is most similar if that is >= `cutoff`, else starts a new Cluster. No
    fixed number of groups. A Mention sits in one group only; a Suggestion may
    therefore appear in several groups.
    """
    if not mentions:
        return []
    if len(mentions) < MIN_MENTIONS_TO_SPLIT:
        return [mentions]
    if embed is None:
        from ingestion.load.suggestions import _embed_texts as embed
    vecs = np.asarray(embed([_mention_text(m) for m in mentions]), dtype="float64")
    vecs = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)
    groups: List[List[int]] = []
    sums: List[np.ndarray] = []
    for i, v in enumerate(vecs):
        best, best_sim = -1, -1.0
        for g, total in enumerate(sums):
            sim = float(v @ total) / max(float(np.linalg.norm(total)), 1e-12)
            if sim > best_sim:
                best, best_sim = g, sim
        if best >= 0 and best_sim >= cutoff:
            groups[best].append(i)
            sums[best] = sums[best] + v
        else:
            groups.append([i])
            sums.append(v.copy())
    return [[mentions[i] for i in g] for g in groups]


def mention_weight(m: Mention, today: date, half_life_years: float) -> float:
    sign = 1.0 if m.polarity == "positive" else -1.0
    old = (today - m.date) > timedelta(days=365.25 * half_life_years)
    return sign * (0.5 if old else 1.0)


def member_lines(group: List[Mention]) -> Dict[str, Dict[str, Any]]:
    """Collapse a group's Mentions to one line per Suggestion name."""
    lines: Dict[str, Dict[str, Any]] = {}
    for m in group:
        key = normalise_name(m.name)
        e = lines.setdefault(key, {"name": m.name, "mentions": []})
        e["mentions"].append(m)
    return lines


LABEL_PROMPT = """Grupo de sugestões da comunidade, tipo "{kind}". Escreva (1) um rótulo curto em português para o propósito comum (ex.: "Produtos brasileiros") e (2) para cada negócio uma linha curta reescrita dizendo para que serve e por quê. Não cite mensagens, autores nem telefones.
Responda em JSON: {{"label": "...", "lines": {{"<nome>": "<linha>"}}}}.

{members}
"""


async def build_cluster_entry(
    kind: Kind,
    group: List[Mention],
    cfg: Any,
    llm_cfg: Any,
    client: httpx.AsyncClient,
    today: date,
    community: frozenset = frozenset(),
) -> ClusterEntry:
    lines = member_lines(group)
    members: List[ClusterMember] = []
    scores: Dict[str, float] = {}
    for key, e in lines.items():
        ms: List[Mention] = e["mentions"]
        members.append(
            ClusterMember(
                name=e["name"],
                thumbs_up=sum(m.polarity == "positive" for m in ms),
                thumbs_down=sum(m.polarity == "negative" for m in ms),
                last_date=max(m.date for m in ms),
                items=list(dict.fromkeys(i for m in ms for i in m.items)),
                community_business=key in community,
            )
        )
        scores[e["name"]] = sum(
            mention_weight(m, today, cfg.ranking_half_life_years) for m in ms
        )
    # best first; ties to the most recent. Every member stays stored.
    members.sort(key=lambda m: (scores[m.name], m.last_date), reverse=True)
    top = [m for m in members if scores[m.name] > 0][: cfg.summary_size]
    n_more = len([m for m in members if scores[m.name] > 0]) - len(top)

    brief = "\n".join(
        f"- {m.name}: itens={', '.join(m.items) or '-'}; contextos="
        + " | ".join(
            dict.fromkeys(
                x.context
                for x in lines[normalise_name(m.name)]["mentions"]
                if x.context
            )
        )
        for m in (top or members[:5])
    )
    out: Optional[dict] = await chat_json(
        client, LABEL_PROMPT.format(kind=kind.value, members=brief), llm_cfg
    )
    label = str((out or {}).get("label") or "").strip() or kind.value
    said: Dict[str, str] = {
        normalise_name(str(k)): str(v)
        for k, v in ((out or {}).get("lines") or {}).items()
    }

    parts = []
    for m in top:
        counts = f"{m.thumbs_up}👍" + (f"/{m.thumbs_down}👎" if m.thumbs_down else "")
        line = said.get(normalise_name(m.name)) or ", ".join(m.items)
        parts.append(
            f"{m.name} ({counts}, última menção {m.last_date.isoformat()})"
            + (f": {line}" if line else "")
        )
    summary = "; ".join(parts) + (f"; +{n_more} outras" if n_more > 0 else "")
    return ClusterEntry(
        kind=kind,
        label=label,
        thumbs_up=sum(m.thumbs_up for m in members),
        thumbs_down=sum(m.thumbs_down for m in members),
        last_date=max(m.last_date for m in members),
        members=members,
        summary=summary or label,
    )


async def build_clusters(
    suggestions: List[Suggestion],
    cfg: Any,
    llm_cfg: Any,
    client: httpx.AsyncClient,
    today: Optional[date] = None,
    dense_embed: Optional[Callable[[List[str]], List[List[float]]]] = None,
    max_concurrency: int = 16,
) -> List[ClusterEntry]:
    """One or more Cluster entries per Kind from the stored Suggestions."""
    today = today or date.today()
    entries: List[ClusterEntry] = []
    sem = asyncio.Semaphore(max_concurrency)

    async def entry_for(kind: Kind, group: List[Mention], community: frozenset):
        async with sem:  # one LLM call (label + summary) per Cluster, in parallel
            return await build_cluster_entry(
                kind, group, cfg, llm_cfg, client, today, community
            )

    jobs = []
    for kind in Kind:
        kind_sugg = [s for s in suggestions if s.kind == kind]
        counted = [m for s in kind_sugg for m in s.counted]
        community = frozenset(
            normalise_name(s.name) for s in kind_sugg if s.community_business
        )
        for group in cluster_mentions(
            kind, counted, dense_embed, cfg.similarity_cutoff
        ):
            jobs.append((kind, entry_for(kind, group, community)))
    built = await asyncio.gather(*[j for _, j in jobs])
    taken: Dict[Kind, set] = {}
    for (kind, _), entry in zip(jobs, built):
        # point id = md5(kind|label): labels must be unique per Kind
        seen = taken.setdefault(kind, set())
        base, n = entry.label, 2
        while entry.label in seen:
            entry.label = f"{base} ({n})"
            n += 1
        seen.add(entry.label)
        entries.append(entry)
    return entries
