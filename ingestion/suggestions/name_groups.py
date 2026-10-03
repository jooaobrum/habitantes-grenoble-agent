"""Second-tier name grouping: which differently written names are one business?

Deterministic and auditable, three rules applied in order:
1. Same compact key: case, accents, articles, type words ("restaurante", "pizzeria"),
   spacing and punctuation ignored ("Casa Barrio Latino" = "Barriolatino").
2. Near-equal compact keys (small spelling differences: "Barril Latino").
3. Same distinctive words: cuisine/food words, cities and other generic words are
   dropped, then equal sets merge ("Natal Grenoble" = "Natal", "Yamato" = "Yamato
   Ramen"), so "Tacos de Lyon" and "Tacos" stay apart (no identity left).
Looser matches (one name's distinctive words contained in another's: "Kabuki" vs
"Kabuki Canton") are NOT applied: a short name can fit several places ("Come Va"
inside both "Come Prima" and "Come M14ma"), so they are returned as suggestions.

Names made only of generic words ("Restaurante brasileiro", "Pizzeria", "bar") have
no identity: they are not valid Suggestions and are returned apart so callers drop them.
Manual decisions (config/suggestion_name_aliases.yaml) override the rules: names that
are the same business, and pairs that must stay apart. An LLM judge
was tried for the rest and rejected: it merged different places that only shared a
cuisine, so its output cannot be trusted without a human.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from habitantes.domain.suggestions import Kind
from ingestion.suggestions.extract import Mention
from ingestion.suggestions.merge import normalise_name

TYPE_WORDS = {
    "restaurante", "restaurant", "resto", "cafe", "bar", "pizzeria", "pizza",
    "snack", "casa", "bistro", "bistrot", "brasserie", "pub", "lanchonete",
    "padaria", "boulangerie", "loja", "magasin", "epicerie",
}  # fmt: skip
# Words that describe a cuisine, a place type or a city: never an identity on their own.
GENERIC_WORDS = TYPE_WORDS | {
    "brasileiro", "brasileira", "brasil", "brazil", "brazuca", "latino", "latina",
    "japones", "japonesa", "chines", "chinesa", "indiano", "indiana", "libanes",
    "libanesa", "mexicano", "mexicana", "italiano", "italiana", "frances", "francesa",
    "tacos", "sushi", "ramen", "burger", "hamburguer", "kebab", "thai", "rodizio",
    "churrascaria", "pizzaria", "universitario", "universitaire", "bar",
    "grenoble", "lyon", "paris", "echirolles", "centre", "centro", "grill", "express",
    "do", "da", "de", "du", "des", "the", "and", "e", "et", "ou", "no", "na", "em",
    "mercado", "supermercado", "mercearia", "acougue", "otica", "optique", "farmacia",
    "pharmacie", "dentista", "dentiste", "medico", "medecin", "ginecologista", "comida",
    "hotel", "hospital", "clinica", "cabeleireiro", "barbeiro", "salao", "academia",
    "escola", "universidade", "banco", "igreja", "aeroporto", "estacao", "gare",
    "advogado", "advogada", "avocat", "contador", "contadora", "psicologo", "psicologa",
    "fisioterapeuta", "dermatologista", "pediatra", "oftalmologista", "ortopedista",
    "cardiologista", "nutricionista", "eletricista", "encanador", "mecanico", "pedreiro",
    "costureira", "manicure", "tradutor", "tradutora", "professor", "professora",
    "hostel", "albergue", "camping",
}  # fmt: skip
FUZZY_MIN_LEN = 8
FUZZY_RATIO = 0.82


DEFAULT_ALIASES_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "suggestion_name_aliases.yaml"
)


@dataclass
class Aliases:
    """Manual decisions: `same` groups (canonical, compact keys, regexes) and `separate` pairs."""

    same: List[Tuple[str, frozenset, List[re.Pattern], Optional[Kind]]] = field(
        default_factory=list
    )
    separate: List[Tuple[str, str]] = field(default_factory=list)  # compact keys
    keep: frozenset = frozenset()  # normalised names exempt from the generic-name drop

    def same_index(self, name: str) -> Optional[int]:
        key, norm = compact_key(name), normalise_name(name)
        for i, (_, keys, patterns, _kind) in enumerate(self.same):
            if key in keys or any(p.search(norm) for p in patterns):
                return i
        return None


def load_aliases(path: Optional[Path] = None) -> Aliases:
    """Aliases from yaml; a missing file means no manual decisions."""
    path = path or DEFAULT_ALIASES_PATH
    if not path.exists():
        return Aliases()
    raw: Dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = Aliases()
    for e in raw.get("same", []):
        out.same.append(
            (
                str(e["canonical"]),
                frozenset(compact_key(n) for n in e.get("names", [])),
                [re.compile(p) for p in e.get("match", [])],
                Kind(e["kind"]) if e.get("kind") else None,
            )
        )
    for a, b in raw.get("separate", []):
        out.separate.append((compact_key(a), compact_key(b)))
    out.keep = frozenset(normalise_name(n) for n in raw.get("keep", []))
    return out


def _words(name: str) -> List[str]:
    return normalise_name(name).split()


def compact_key(name: str) -> str:
    """normalise_name + type words removed + spaces removed ("Casa Barrio Latino" -> "barriolatino")."""
    words = [w for w in _words(name) if w not in TYPE_WORDS]
    return "".join(words or _words(name))


def distinctive(name: str) -> frozenset:
    words = [w for w in _words(name) if w not in GENERIC_WORDS]
    long_words = [w for w in words if len(w) > 2]
    # Short brand names ("B&M", "H&M", "BK") have only short words: keep them whole.
    return frozenset(long_words or (words if len(words) == len(_words(name)) else []))


def qualifiers(name: str) -> frozenset:
    """Generic words that qualify a name but are not mere type words: cities,
    nationalities, cuisines ("Consulado de Paris" vs "Consulado Italiano de Grenoble")."""
    return frozenset(
        w
        for w in _words(name)
        if w in GENERIC_WORDS and w not in TYPE_WORDS and len(w) > 2
    )


def distinctive_key(name: str) -> str:
    """Distinctive words joined without spaces; the base for spelling-similarity."""
    words = [w for w in _words(name) if w in distinctive(name)]
    return "".join(words)


def is_generic(name: str) -> bool:
    """No distinctive word ("Restaurante brasileiro", "Pizzeria", "bar") or only digits ("168")."""
    d = distinctive(name)
    return not d or all(w.isdigit() for w in d)


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def _conflict(a: str, b: str) -> bool:
    """Both names carry a qualifier and they differ: different branches/places."""
    qa, qb = qualifiers(a), qualifiers(b)
    return bool(qa and qb and qa != qb)


MIN_SHORT_MENTIONS = 3  # a name of <= 2 letters ("B&M", "H&M") needs this many Mentions


def group_names(
    names: List[str],
    aliases: Optional[Aliases] = None,
    counts: Optional[Dict[str, int]] = None,
) -> Tuple[List[List[str]], List[str], List[Tuple[str, str]]]:
    """(groups of names for one business, generic names left unassigned,
    suggested merges not applied as (shorter name, longer name)).

    `counts` (Mentions per name) lets very short names ("F1", "C7", "GI") be dropped
    unless they are frequent enough to be a real brand."""
    aliases = aliases or Aliases()
    covered = {
        n
        for n in names
        if aliases.same_index(n) is not None or normalise_name(n) in aliases.keep
    }
    by_compact: Dict[str, int] = defaultdict(int)
    for n in names:
        by_compact[compact_key(n)] += (counts or {}).get(n, MIN_SHORT_MENTIONS)

    def invalid(n: str) -> bool:
        short = (
            len(compact_key(n)) <= 2 and by_compact[compact_key(n)] < MIN_SHORT_MENTIONS
        )
        return is_generic(n) or short

    generic = [n for n in names if n not in covered and invalid(n)]
    named = [n for n in names if n not in generic]
    uf = _UnionFind(named)
    keys_of = {n: compact_key(n) for n in named}

    def union(a: str, b: str) -> None:
        """Union unless a manual `separate` pair would end up in one group."""
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            return
        ka = {keys_of[n] for n in named if uf.find(n) == ra}
        kb = {keys_of[n] for n in named if uf.find(n) == rb}
        if any(
            (x in ka and y in kb) or (y in ka and x in kb) for x, y in aliases.separate
        ):
            return
        uf.union(a, b)

    first: Dict[int, str] = {}
    for n in named:  # manual `same` first: they always win
        i = aliases.same_index(n)
        if i is not None:
            if i in first:
                uf.union(first[i], n)
            else:
                first[i] = n
    by_key: Dict[str, List[str]] = defaultdict(list)
    for n in named:
        by_key[compact_key(n)].append(n)
    for group in by_key.values():  # rule 1
        for other in group[1:]:
            union(group[0], other)
    by_dkey: Dict[str, List[str]] = defaultdict(list)
    for n in named:
        by_dkey[distinctive_key(n)].append(n)
    dkeys = [k for k in by_dkey if len(k) >= FUZZY_MIN_LEN]
    for i, a in enumerate(
        dkeys
    ):  # rule 2 (on distinctive words: "Grenoble" never counts)
        for b in dkeys[i + 1 :]:
            if difflib.SequenceMatcher(None, a, b).ratio() >= FUZZY_RATIO:
                union(by_dkey[a][0], by_dkey[b][0])
    dist = {n: distinctive(n) for n in named}
    for i, a in enumerate(named):  # rule 3
        for b in named[i + 1 :]:
            if dist[a] and dist[a] == dist[b] and not _conflict(a, b):
                union(a, b)
    suggestions: List[Tuple[str, str]] = []
    for a in named:
        for b in named:
            if dist[a] < dist[b] and uf.find(a) != uf.find(b):
                suggestions.append((a, b))
    out: Dict[str, List[str]] = defaultdict(list)
    for n in named:
        out[uf.find(n)].append(n)
    return list(out.values()), generic, suggestions


class GroupedMention(Mention):
    """A raw Mention, unchanged, plus `group`: the canonical name of its business.

    `name` and `kind` stay exactly as extracted. When a business has a single written
    name, `group` simply repeats `name`. `group_kind` is the Kind where the business
    has the most Mentions: a business named under several Kinds (Carrefour as
    Markets & Groceries and as Shops) gets that one Kind."""

    group: str
    group_kind: Kind


def group_mentions(
    mentions: List[Mention], aliases: Optional[Aliases] = None
) -> Tuple[List[GroupedMention], Dict[str, Any]]:
    """Group Mentions by business (all Kinds); drop generic names.

    Names are grouped within each Kind, then the same business found under several
    Kinds is unified: it takes the Kind with the most Mentions (`group_kind`).
    Returns (grouped Mentions, report); the report counts what each step did and lists
    the dropped generic names so a reviewer can check nothing real was lost.
    """
    aliases = aliases or Aliases()
    by_kind: Dict[Kind, List[Mention]] = defaultdict(list)
    for m in mentions:
        by_kind[m.kind].append(m)
    kept: List[Tuple[Mention, str]] = []  # (mention, canonical within its Kind)
    report: Dict[str, Any] = {"kinds": {}, "dropped_generic": [], "rekinded": []}
    for kind, ms in by_kind.items():
        names = sorted({m.name.strip() for m in ms})
        freq = Counter(m.name.strip() for m in ms)
        groups, generic, _ = group_names(names, aliases, dict(freq))
        canonical: Dict[str, str] = {}
        for g in groups:
            idx = {aliases.same_index(n) for n in g} - {None}
            shown = (
                aliases.same[min(idx)][0]
                if idx
                else sorted(g, key=lambda n: (-freq[n], len(n), n))[0]
            )
            for n in g:
                canonical[n] = shown
        gen = set(generic)
        dropped = [m for m in ms if m.name.strip() in gen]
        kept += [
            (m, canonical[m.name.strip()]) for m in ms if m.name.strip() not in gen
        ]
        report["kinds"][kind.value] = {
            "mentions": len(ms),
            "kept": len(ms) - len(dropped),
            "dropped_generic": len(dropped),
            "raw_names": len(names),
            "businesses": len(groups),
        }
        report["dropped_generic"] += [
            {"kind": kind.value, "name": n, "mentions": freq[n]}
            for n in sorted(gen, key=lambda n: -freq[n])
        ]

    # Same business under several Kinds: the Kind with the most Mentions wins.
    votes: Dict[str, Counter] = defaultdict(Counter)  # business key -> Kind counts
    shown_by: Dict[Tuple[str, Kind], Counter] = defaultdict(Counter)
    for m, canon in kept:
        votes[compact_key(canon)][m.kind] += 1
        shown_by[(compact_key(canon), m.kind)][canon] += 1
    winner: Dict[str, Tuple[Kind, str]] = {}
    fixed = {compact_key(a[0]): a[3] for a in aliases.same if a[3] is not None}
    for key, c in votes.items():
        kind = (
            fixed.get(key)
            or sorted(c, key=lambda k: (-c[k], k in VAGUE_KINDS, k.value))[0]
        )
        shown = shown_by[(key, kind)] or shown_by[(key, next(iter(c)))]
        winner[key] = (kind, shown.most_common(1)[0][0])
        if len(c) > 1:
            report["rekinded"].append(
                {
                    "group": winner[key][1],
                    "group_kind": kind.value,
                    "kinds": {k.value: v for k, v in c.most_common()},
                }
            )
    report["rekinded"].sort(key=lambda r: -sum(r["kinds"].values()))
    out = [
        GroupedMention(
            **{
                **m.model_dump(),
                "group": winner[compact_key(canon)][1],
                "group_kind": winner[compact_key(canon)][0],
            }
        )
        for m, canon in kept
    ]
    return out, report


VAGUE_KINDS = frozenset({Kind.OTHER, Kind.PLACES_AND_OUTINGS, Kind.SHOPS})
GROUPED_FILENAME = "grouped_mentions.jsonl"


def main() -> None:  # pragma: no cover - CLI glue
    """`python ingestion/suggestions/name_groups.py <chat artifacts dir>`: mentions.jsonl -> grouped_mentions.jsonl."""
    import argparse

    from ingestion.suggestions.mentions import read_mentions

    p = argparse.ArgumentParser(description=main.__doc__)
    p.add_argument("dir", type=Path)
    args = p.parse_args()
    grouped, report = group_mentions(
        read_mentions(args.dir / "mentions.jsonl"), load_aliases()
    )
    out = args.dir / GROUPED_FILENAME
    out.write_text(
        "".join(g.model_dump_json() + "\n" for g in grouped), encoding="utf-8"
    )
    print(f"{len(grouped)} grouped mentions -> {out}")
    for kind, s in sorted(report["kinds"].items(), key=lambda kv: -kv[1]["mentions"]):
        print(
            f"  {kind:24s} mentions={s['mentions']:5d} kept={s['kept']:5d} "
            f"dropped_generic={s['dropped_generic']:4d} names={s['raw_names']:4d} -> businesses={s['businesses']:4d}"
        )


if __name__ == "__main__":
    main()
