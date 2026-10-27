"""Recover the chat messages behind each grouped Mention (author-free text only).

Mentions keep no source text, only a reworded Context. This matches each Mention back to
the parsed chat by date (and +-1 day) and by the words of its name, so later steps (such as
subcategory assignment) can read what members actually wrote. The match is heuristic: it
finds messages that name the business, not necessarily the very message that was extracted.
Measured on the real export: 95% of Mentions and 95% of groups match.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

from ingestion.suggestions.extract import scrub_phones

_STOP = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "la",
    "le",
    "les",
    "du",
    "des",
    "the",
    "e",
    "et",
    "o",
    "a",
    "os",
    "as",
}
MAX_MESSAGES_PER_GROUP = 8
MAX_CHARS = 420


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s)


def name_tokens(name: str) -> List[str]:
    words = _norm(name).split()
    return [
        w
        for w in words
        if w not in _STOP and (len(w) >= 3 or w.isdigit() or len(words) == 1)
    ]


def index_messages(messages: List[Dict[str, Any]]) -> Dict[str, List[tuple]]:
    """day (YYYY-MM-DD) -> [(normalised text, original text)] from parsed chat rows."""
    by: Dict[str, List[tuple]] = defaultdict(list)
    for m in messages:
        text = str(m.get("message", "") or "")
        by[str(m["timestamp"])[:10]].append((" " + _norm(text) + " ", text))
    return by


def messages_for(name: str, when: str, by_day: Dict[str, List[tuple]]) -> List[str]:
    """Messages on `when` (else the day before/after) that contain every word of `name`."""
    tokens = name_tokens(name)
    if not tokens:
        return []
    d0 = date.fromisoformat(when)
    for offset in (0, -1, 1):
        hits = [
            text
            for norm, text in by_day.get(str(d0 + timedelta(days=offset)), [])
            if all(f" {t} " in norm or (len(t) >= 5 and t in norm) for t in tokens)
        ]
        if hits:
            return hits
    return []


def source_messages(
    rows: List[Dict[str, Any]], by_day: Dict[str, List[tuple]]
) -> Dict[str, Dict[str, Any]]:
    """group -> {kind, mentions, matched, messages (phones scrubbed, truncated, deduped)}."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        g = out.setdefault(
            r["group"], {"kind": r["kind"], "mentions": 0, "matched": 0, "messages": []}
        )
        g["mentions"] += 1
        hits = messages_for(r["name"], r["date"], by_day)
        if hits:
            g["matched"] += 1
            for text in hits[:3]:
                text = scrub_phones(text.replace("\n", " "))[:MAX_CHARS]
                if (
                    text not in g["messages"]
                    and len(g["messages"]) < MAX_MESSAGES_PER_GROUP
                ):
                    g["messages"].append(text)
    return out


def main() -> None:  # pragma: no cover - CLI glue
    """`python ingestion/suggestions/source_messages.py <chat artifacts dir>`."""
    import argparse

    import pandas as pd

    p = argparse.ArgumentParser(description=main.__doc__)
    p.add_argument("dir", type=Path)
    args = p.parse_args()
    rows = [
        json.loads(line) for line in open(args.dir / "grouped_mentions_filtered.jsonl")
    ]
    df = pd.read_csv(args.dir / "classified.csv")
    by_day = index_messages(df.to_dict("records"))
    res = source_messages(rows, by_day)
    out = args.dir / "quality_gate" / "source_messages.jsonl"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for g, v in res.items():
            f.write(json.dumps({"group": g, **v}, ensure_ascii=False) + "\n")
    ok = sum(v["matched"] for v in res.values())
    total = sum(v["mentions"] for v in res.values())
    print(
        f"{ok}/{total} Mentions matched ({ok / total:.0%}); {len(res)} groups -> {out}"
    )


if __name__ == "__main__":
    main()
