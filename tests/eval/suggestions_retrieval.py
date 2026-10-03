"""Retrieval quality of `search_suggestions` against the pseudo-golden dataset.

For each question in suggestions_pseudo_golden.tsv, runs the same search the agent
runs and checks which expected Suggestions come back:

- shown   : among the members the agent would be given (top members + long tail)
- cluster : among ALL members of the returned Clusters (retrieval found the right
            Cluster, but display limits may have hidden the name)
- stored  : anywhere in the collection (an upper bound set by ingestion, not search)

Requires the Suggestions collection to be loaded (make suggestions) and
OPENAI_API_KEY. Run: PYTHONPATH=.:api/src uv run python tests/eval/suggestions_retrieval.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

GENERIC = {"le", "la", "les", "de", "du", "des", "et", "the", "chez", "restaurant"}
DEFAULT_TSV = Path(__file__).parent / "suggestions_pseudo_golden.tsv"


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"\([^)]*\)", " ", s.lower())
    return " ".join(
        w for w in re.sub(r"[^a-z0-9]+", " ", s).split() if w not in GENERIC
    )


def names_match(a: str, b: str) -> bool:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    ta, tb = set(na.split()), set(nb.split())
    return len(ta & tb) / len(ta | tb) >= 0.6


def load_dataset(path: Path = DEFAULT_TSV) -> List[Dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.reader(f, delimiter="\t"):
            if len(r) >= 2 and r[0] != "Question" and r[0].strip() and r[1].strip():
                rows.append(
                    {
                        "question": r[0].strip(),
                        "expected": [x.strip() for x in r[1].split(",") if x.strip()],
                    }
                )
    return rows


def split_dataset(
    rows: List[Dict[str, Any]], part: str, tune_size: int = 25, seed: int = 42
) -> List[Dict[str, Any]]:
    """Seeded split: `tune` is the only part to iterate on, `holdout` is reported.

    Tuning code, prompts or keywords on all questions would overfit the dataset,
    so every tweak is judged on `tune` and the final numbers come from `holdout`.
    """
    import random

    idx = list(range(len(rows)))
    random.Random(seed).shuffle(idx)
    tune = set(idx[:tune_size])
    if part == "tune":
        return [r for i, r in enumerate(rows) if i in tune]
    if part == "holdout":
        return [r for i, r in enumerate(rows) if i not in tune]
    return rows


def found(expected: List[str], pool: List[str]) -> List[str]:
    return [e for e in expected if any(names_match(e, p) for p in pool)]


def evaluate_case(case: Dict[str, Any], search, all_names: List[str]) -> Dict[str, Any]:
    res = search(case["question"])
    clusters = res.get("clusters", [])
    shown = [m["name"] for c in clusters for m in c.get("members", [])]
    cluster_all = [
        m["name"] for c in clusters for m in c.get("all_members", c.get("members", []))
    ]
    exp = case["expected"]
    hit_shown, hit_cluster, hit_stored = (
        found(exp, shown),
        found(exp, cluster_all),
        found(exp, all_names),
    )
    return {
        **case,
        "shown": shown,
        "hit_shown": hit_shown,
        "hit_cluster": hit_cluster,
        "hit_stored": hit_stored,
        "no_results": bool(res.get("no_results")),
        "labels": [c.get("label") for c in clusters],
    }


def summarise(results: List[Dict[str, Any]]) -> Dict[str, float]:
    n = len(results)
    tot = sum(len(r["expected"]) for r in results)

    def micro(k: str) -> float:
        return sum(len(r[k]) for r in results) / tot if tot else 0.0

    return {
        "questions": n,
        "recall_shown": round(micro("hit_shown"), 3),
        "recall_cluster": round(micro("hit_cluster"), 3),
        "recall_stored": round(micro("hit_stored"), 3),
        "any_hit_shown": round(sum(bool(r["hit_shown"]) for r in results) / n, 3),
        "no_results": round(sum(r["no_results"] for r in results) / n, 3),
    }


def main() -> None:  # pragma: no cover - needs Qdrant + embeddings
    from habitantes.config import load_settings
    from habitantes.domain.tools.suggestions import search_clusters

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tsv", type=Path, default=DEFAULT_TSV)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument(
        "--split",
        choices=["tune", "holdout", "all"],
        default="tune",
        help="tune = iterate on this; holdout = report this; default tune",
    )
    p.add_argument("--details", action="store_true")
    args = p.parse_args()

    from habitantes.domain.tools import search as _search

    client = _search._get_qdrant_client()
    name = load_settings().suggestions.collection_name
    stored: List[str] = []
    off = None
    while True:
        pts, off = client.scroll(name, limit=256, offset=off, with_payload=True)
        for pt in pts:
            stored += [m["name"] for m in (pt.payload or {}).get("members", [])]
        if off is None:
            break

    results = [
        evaluate_case(c, search_clusters, stored)
        for c in split_dataset(load_dataset(args.tsv), args.split)
    ]
    print(json.dumps(summarise(results), indent=1))
    if args.details:
        for r in results:
            miss = [e for e in r["expected"] if e not in r["hit_shown"]]
            tag = "ok " if not miss else "MISS"
            print(
                f"{tag} {r['question'][:70]} | missing: {miss} | stored: {r['hit_stored']}"
            )
    if args.out:
        args.out.write_text(
            json.dumps(
                {"summary": summarise(results), "cases": results},
                ensure_ascii=False,
                indent=1,
            )
        )


if __name__ == "__main__":
    main()
