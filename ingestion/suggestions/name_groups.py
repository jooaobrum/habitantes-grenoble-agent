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
no identity; they are returned apart for review instead of being merged. An LLM judge
was tried for the rest and rejected: it merged different places that only shared a
cuisine, so its output cannot be trusted without a human.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

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
    "churrascaria", "pizzaria", "universitario", "universitaire", "bairro", "bar",
    "grenoble", "lyon", "paris", "echirolles", "centre", "centro", "grill", "express",
    "do", "da", "de", "du", "des", "the", "and", "e", "et", "ou", "no", "na", "em",
}  # fmt: skip
FUZZY_MIN_LEN = 8
FUZZY_RATIO = 0.82


def _words(name: str) -> List[str]:
    return normalise_name(name).split()


def compact_key(name: str) -> str:
    """normalise_name + type words removed + spaces removed ("Casa Barrio Latino" -> "barriolatino")."""
    words = [w for w in _words(name) if w not in TYPE_WORDS]
    return "".join(words or _words(name))


def distinctive(name: str) -> frozenset:
    return frozenset(w for w in _words(name) if w not in GENERIC_WORDS and len(w) > 2)


def is_generic(name: str) -> bool:
    """No distinctive word at all: "Restaurante brasileiro", "Pizzeria", "bar"."""
    return not distinctive(name)


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


def group_names(
    names: List[str],
) -> Tuple[List[List[str]], List[str], List[Tuple[str, str]]]:
    """(groups of names for one business, generic names left unassigned,
    suggested merges not applied as (shorter name, longer name))."""
    generic = [n for n in names if is_generic(n)]
    named = [n for n in names if not is_generic(n)]
    uf = _UnionFind(named)
    by_key: Dict[str, List[str]] = defaultdict(list)
    for n in named:
        by_key[compact_key(n)].append(n)
    for group in by_key.values():  # rule 1
        for other in group[1:]:
            uf.union(group[0], other)
    keys = [k for k in by_key if len(k) >= FUZZY_MIN_LEN]
    for i, a in enumerate(keys):  # rule 2
        for b in keys[i + 1 :]:
            if difflib.SequenceMatcher(None, a, b).ratio() >= FUZZY_RATIO:
                uf.union(by_key[a][0], by_key[b][0])
    dist = {n: distinctive(n) for n in named}
    for i, a in enumerate(named):  # rule 3
        for b in named[i + 1 :]:
            if dist[a] == dist[b]:
                uf.union(a, b)
    suggestions: List[Tuple[str, str]] = []
    for a in named:
        for b in named:
            if dist[a] < dist[b] and uf.find(a) != uf.find(b):
                suggestions.append((a, b))
    out: Dict[str, List[str]] = defaultdict(list)
    for n in named:
        out[uf.find(n)].append(n)
    return list(out.values()), generic, suggestions
