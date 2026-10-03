"""Quality gate on grouped Suggestions: keep only real named businesses/places/products.

Jev answers yes/no questions about each group (name, variants, Kind, items, contexts).
The decision question is `valid`; the other questions only explain a rejection.
Frequency is not a quality signal (real-business rate was the same for single- and
multi-mention names), so no group is dropped for being rare; a single-mention group
only has to clear a stricter cutoff.

Pure functions (`build_groups`, `decide`, `pick_cutoff`) are unit-tested; the CLI
calibrates the cutoff on proxy labels, scores every group and writes the filtered file.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

GATE_QUESTIONS: Dict[str, str] = {
    "valid": (
        "Is `name` a valid Suggestion: a specific, named business, place, product or "
        "service that a person can go to or buy from, written as a proper name? "
        "Answer NO for generic words (a type of place, food or profession), cities or "
        "neighbourhoods, private people, apps, websites, platforms, banks, phone "
        "operators, public services, associations and one-off events."
    ),
    "generic": (
        "Is `name` only a generic word or category (a type of place, food, product or "
        "profession) and not the name of one specific business?"
    ),
    "person": "Is `name` the name of a private individual (not a business)?",
    "platform_or_public": (
        "Is `name` an app, website, online platform, bank, phone operator, public "
        "service, administration or association?"
    ),
}


OUTING_EXCEPTION = (
    " Exception: for kind 'Places & Outings', a specific named destination or outing "
    "spot (ski resort, mountain, lake, trail, park, village or town worth a visit) IS valid."
)


PRACTITIONER_KINDS = frozenset(
    {
        "Doctors",
        "Dentists",
        "Translators",
        "Professional Services",
        "Salons & Beauty",
        "Courses & Teachers",
        "Vets & Pets",
        "Gyms & Sports",
    }
)
PRACTITIONER_EXCEPTION = (
    " Exception: for this kind, a named practitioner who offers a professional service "
    "(doctor, dentist, translator, hairdresser, teacher, lawyer, therapist, coach) IS "
    "valid: the person is the business. A private person who offers no service is not."
)


def questions_for(kind: str) -> Dict[str, str]:
    """The gate questions, with the exceptions of the Kind: destinations are valid for
    Places & Outings, named practitioners for the professional Kinds."""
    q = dict(GATE_QUESTIONS)
    if kind == "Places & Outings":
        q["valid"] = q["valid"] + OUTING_EXCEPTION
    elif kind in PRACTITIONER_KINDS:
        q["valid"] = q["valid"] + PRACTITIONER_EXCEPTION
        q["person"] = (
            "Is `name` a private individual who offers no professional service "
            "(not a named doctor, dentist, translator, hairdresser, teacher or similar)?"
        )
    return q


@dataclass
class GateGroup:
    group: str
    kind: str
    variants: List[str]
    mentions: int
    thumbs_up: int
    thumbs_down: int
    items: List[str] = field(default_factory=list)
    contexts: List[str] = field(default_factory=list)

    def state(self) -> Dict[str, Any]:
        """What Jev sees about the group (no author, no phone: Mentions are author-free)."""
        return {
            "name": self.group,
            "variants": self.variants[:6],
            "kind": self.kind,
            "mentions": self.mentions,
            "items": self.items[:5],
            "contexts": [c[:140] for c in self.contexts[:2]],
        }


def build_groups(rows: List[Dict[str, Any]]) -> List[GateGroup]:
    """One GateGroup per `group` of grouped_mentions rows."""
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["group"]].append(r)
    out = []
    for g, rs in by.items():
        up = sum(r["polarity"] == "positive" for r in rs)
        items = Counter(i for r in rs for i in r["items"])
        positives = [r["context"] for r in rs if r["polarity"] == "positive"]
        out.append(
            GateGroup(
                group=g,
                kind=Counter(r["kind"] for r in rs).most_common(1)[0][0],
                variants=[n for n, _ in Counter(r["name"] for r in rs).most_common()],
                mentions=len(rs),
                thumbs_up=up,
                thumbs_down=len(rs) - up,
                items=[i for i, _ in items.most_common(5)],
                contexts=(positives or [r["context"] for r in rs])[:2],
            )
        )
    return out


def decide(
    valid: Optional[float], mentions: int, cutoff: float, single_cutoff: float
) -> bool:
    """Keep a group when Jev says valid; a single-mention group needs the stricter cutoff.
    A group Jev could not score (None) is dropped, like an unclassifiable window."""
    if valid is None:
        return False
    return valid >= (single_cutoff if mentions <= 1 else cutoff)


def pick_cutoff(
    rows: List[Tuple[float, bool]], min_recall: float = 0.9
) -> Optional[float]:
    """Highest cutoff that keeps >= `min_recall` of the really valid groups.

    `rows` are (valid score, is really valid). The highest cutoff is the strictest
    gate, hence the fewest non-business groups left."""
    positives = [s for s, ok in rows if ok]
    if not positives:
        return None
    best = None
    for c in [i / 100 for i in range(1, 100)]:
        if sum(s >= c for s in positives) / len(positives) >= min_recall:
            best = c
    return best


def gate_metrics(rows: List[Tuple[float, bool]], cutoff: float) -> Dict[str, float]:
    """On labelled (score, really valid) rows: kept share, non-business share among
    kept groups, and the share of really valid groups kept (recall)."""
    kept = [(s, ok) for s, ok in rows if s >= cutoff]
    valid = [s for s, ok in rows if ok]
    return {
        "kept_share": len(kept) / len(rows) if rows else 0.0,
        "non_business_share_kept": (
            sum(not ok for _, ok in kept) / len(kept) if kept else 0.0
        ),
        "recall_valid": (
            sum(s >= cutoff for s in valid) / len(valid) if valid else 0.0
        ),
    }


async def score_groups(
    groups: List[GateGroup],
    client: Any,
    jev: Any,
    concurrency: int = 16,
) -> List[Optional[Dict[str, float]]]:
    """Jev scores for every question and group (None where Jev failed)."""
    from ingestion.preprocess.jev import score_questions

    sem = asyncio.Semaphore(concurrency)

    async def one(g: GateGroup) -> Optional[Dict[str, float]]:
        async with sem:
            return await score_questions(
                client,
                g.state(),
                questions_for(g.kind),
                model=jev.model,
                base_url=jev.base_url,
                max_retries=jev.max_retries,
                retry_base_sleep_s=jev.retry_base_sleep_s,
            )

    return list(await asyncio.gather(*(one(g) for g in groups)))


PROXY_PROMPT = """Avalie cada candidato a 'Sugestão' (extraído de um grupo de brasileiros em Grenoble). Responda em JSON {"r":[{"i":n,"cat":...}]}.
cat = uma de: "negocio_real" (loja, restaurante, médico/clínica, serviço, marca, lugar ou destino específico e nomeado; também profissionais nomeados que oferecem serviço: médico, dentista, tradutor, cabeleireiro, professor, advogado), "generico" (palavra genérica: tipo de lugar, comida, produto, profissão), "app_plataforma" (app, site, plataforma online, banco, operadora), "orgao_publico_ou_assoc", "pessoa_fisica" (pessoa que NÃO oferece serviço profissional), "outro_nao_recomendavel".
Candidatos:
"""


async def proxy_labels(
    groups: List[GateGroup], client: Any, cfg: Any, batch: int = 25
) -> Dict[str, str]:
    """LLM proxy label (category) per group name. Model output, not hand labels."""
    from ingestion.suggestions.llm import chat_json

    out: Dict[str, str] = {}
    for i in range(0, len(groups), batch):
        chunk = groups[i : i + batch]
        lines = "\n".join(
            f'{j}. nome="{g.group}" kind={g.kind} items={g.items[:3]} '
            f"👍={g.thumbs_up} 👎={g.thumbs_down}"
            for j, g in enumerate(chunk)
        )
        res = await chat_json(client, PROXY_PROMPT + lines, cfg)
        for r in (res or {}).get("r", []):
            if isinstance(r.get("i"), int) and 0 <= r["i"] < len(chunk):
                out[chunk[r["i"]].group] = str(r.get("cat", ""))
    return out


def to_json(g: GateGroup, scores: Optional[Dict[str, float]], kept: bool) -> str:
    return json.dumps({**asdict(g), "scores": scores, "kept": kept}, ensure_ascii=False)


DEFAULT_CUTOFF = 0.4  # keeps ~90% of really valid groups on the calibration sample
DEFAULT_SINGLE_CUTOFF = 0.5  # single-mention groups: slightly stricter


def protected_keys(aliases: Any) -> frozenset:
    """Compact keys of businesses the maintainer listed in the alias file (same / kinds /
    community / keep): chosen by hand, so the gate never drops them."""
    from ingestion.suggestions.name_groups import compact_key

    keys = {compact_key(a[0]) for a in aliases.same}
    for a in aliases.same:
        keys |= set(a[1])
    for rules, _default in aliases.splits.values():
        keys |= {compact_key(c) for c, _k, _p in rules}
    keys |= set(aliases.kinds) | set(aliases.community)
    keys |= {compact_key(n) for n in aliases.keep}
    return frozenset(keys)


def apply_gate(
    rows: List[Dict[str, Any]],
    scores_by_group: Dict[str, Optional[Dict[str, float]]],
    cutoff: float = DEFAULT_CUTOFF,
    single_cutoff: float = DEFAULT_SINGLE_CUTOFF,
    protected: frozenset = frozenset(),
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(rows of kept groups, names of dropped groups). Rows are returned untouched.
    Groups whose compact key is in `protected` are always kept."""
    from ingestion.suggestions.name_groups import compact_key

    mentions = Counter(r["group"] for r in rows)
    keep: Dict[str, bool] = {}
    for g, n in mentions.items():
        s = scores_by_group.get(g)
        keep[g] = compact_key(g) in protected or decide(
            s["valid"] if s else None, n, cutoff, single_cutoff
        )
    return (
        [r for r in rows if keep[r["group"]]],
        sorted(g for g, k in keep.items() if not k),
    )


GATE_DIRNAME = "quality_gate"
FILTERED_FILENAME = "grouped_mentions_filtered.jsonl"
_GROUP_FIELDS = (
    "group", "kind", "variants", "mentions", "thumbs_up", "thumbs_down", "items", "contexts",
)  # fmt: skip


def _load(path: Any) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:  # pragma: no cover - needs Jev / LLM access
    """`python ingestion/suggestions/quality_gate.py <chat dir> --step score|apply|measure`.

    score   : Jev scores for every group -> <dir>/quality_gate/scores.jsonl
    apply   : scores -> grouped_mentions_filtered.jsonl (+ dropped_review.md)
    measure : proxy-label fresh random samples of groups before/after/dropped and print
              the non-business share (LLM proxy labels, not hand labels)
    """
    import argparse
    import random
    from pathlib import Path

    import httpx
    from dotenv import load_dotenv

    from ingestion.config import settings

    p = argparse.ArgumentParser(description=main.__doc__)
    p.add_argument("dir", type=Path)
    p.add_argument("--step", choices=["score", "apply", "measure"], required=True)
    p.add_argument("--cutoff", type=float, default=DEFAULT_CUTOFF)
    p.add_argument("--single-cutoff", type=float, default=DEFAULT_SINGLE_CUTOFF)
    p.add_argument("--seed", type=int, default=4242)
    args = p.parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    gdir = args.dir / GATE_DIRNAME
    gdir.mkdir(exist_ok=True)
    rows = _load(args.dir / "grouped_mentions.jsonl")
    groups = build_groups(rows)

    async def run_score() -> None:
        scores = await score_groups(groups, httpx.AsyncClient(timeout=60), settings.jev)
        with open(gdir / "scores.jsonl", "w", encoding="utf-8") as f:
            for g, s in zip(groups, scores):
                f.write(
                    json.dumps({**asdict(g), "scores": s}, ensure_ascii=False) + "\n"
                )
        print(f"scored {sum(s is not None for s in scores)}/{len(groups)} groups")

    def load_scores() -> Dict[str, Optional[Dict[str, float]]]:
        return {r["group"]: r["scores"] for r in _load(gdir / "scores.jsonl")}

    if args.step == "score":
        asyncio.run(run_score())
        return
    scores = load_scores()
    from ingestion.suggestions.name_groups import load_aliases

    kept_rows, dropped = apply_gate(
        rows, scores, args.cutoff, args.single_cutoff, protected_keys(load_aliases())
    )
    if args.step == "apply":
        out = args.dir / FILTERED_FILENAME
        out.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept_rows),
            encoding="utf-8",
        )
        print(
            f"groups {len(groups)} -> {len(groups) - len(dropped)} kept; "
            f"mentions {len(rows)} -> {len(kept_rows)} -> {out}"
        )
        return
    by_name = {g.group: g for g in groups}
    kept = sorted({r["group"] for r in kept_rows})
    rng = random.Random(args.seed)
    cfg = settings.suggestion_llm.model_copy(
        update={"model": "google/gemini-2.5-flash"}
    )

    async def run_measure() -> None:
        cl = httpx.AsyncClient(timeout=60)
        for name, pool, n in (
            ("before gate", sorted(by_name), 200),
            ("after gate", kept, 200),
            ("dropped", dropped, 150),
        ):
            labels = await proxy_labels(
                [by_name[g] for g in rng.sample(pool, min(n, len(pool)))], cl, cfg
            )
            real = sum(c == "negocio_real" for c in labels.values()) / len(labels)
            print(
                f"{name:12s} n={len(labels)} real={real:.0%} non-business={1 - real:.0%}"
            )

    asyncio.run(run_measure())


if __name__ == "__main__":
    main()
