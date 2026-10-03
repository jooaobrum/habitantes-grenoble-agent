"""Draw a seeded random sample of Threads and write them for hand-labelling.

Output is JSONL, one Thread per line. The maintainer fills the empty
`suggestions` list of each Thread (see docs/SUGGESTIONS_EVAL.md). Authors are
replaced by thread-local pseudonyms (M1, M2...) so the file carries no names.
Nothing is labelled here: labels are always hand-written.

Run with `make labelling-sample`.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from ingestion.preprocess.qa_pairs import detect_threads

DEFAULT_SAMPLE_SIZE = 50
DEFAULT_SEED = 42
DEFAULT_MIN_MESSAGES = 3


def thread_record(thread_id: int, thread_df: pd.DataFrame) -> Dict[str, Any]:
    """One labelling record: pseudonymised messages plus an empty label list."""
    pseudo: Dict[str, str] = {}
    messages: List[Dict[str, Any]] = []
    for i, row in enumerate(thread_df.to_dict(orient="records")):
        user = str(row["user"])
        pseudo.setdefault(user, f"M{len(pseudo) + 1}")
        messages.append(
            {
                "idx": i,
                "user": pseudo[user],
                "timestamp": str(row["timestamp"]),
                "message": str(row.get("message", "") or ""),
            }
        )
    return {"thread_id": thread_id, "messages": messages, "suggestions": []}


def draw_sample(
    df: pd.DataFrame,
    thread_gap_h: int,
    n: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
    min_messages: int = DEFAULT_MIN_MESSAGES,
) -> List[Dict[str, Any]]:
    """`n` random Threads (fewer if the chat has fewer), ordered by thread_id.

    `thread_id` is the index from the shared Thread splitting, so it matches the
    ids used by the candidate windows.
    """
    threads = detect_threads(df, thread_gap_h)
    eligible = [
        (tid, t) for tid, t in enumerate(threads) if len(t) >= max(1, min_messages)
    ]
    picked = random.Random(seed).sample(eligible, min(n, len(eligible)))
    return [thread_record(tid, t) for tid, t in sorted(picked, key=lambda p: p[0])]


def write_sample(records: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_classified(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["message"] = df["message"].fillna("")
    return df


def main() -> None:
    from ingestion.config import settings

    root = Path(__file__).parents[2]
    default_csv = (
        root
        / settings.artifacts_dir
        / Path(settings.input_file).stem
        / "classified.csv"
    )
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input", type=Path, default=default_csv, help="classified chat CSV"
    )
    p.add_argument("--output", type=Path, default=None, help="labelling JSONL")
    p.add_argument("--n", type=int, default=DEFAULT_SAMPLE_SIZE)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--min-messages", type=int, default=DEFAULT_MIN_MESSAGES)
    args = p.parse_args()

    out = args.output or args.input.parent / "labelling_sample.jsonl"
    records = draw_sample(
        load_classified(args.input),
        settings.qa.thread_gap_h,
        args.n,
        args.seed,
        args.min_messages,
    )
    write_sample(records, out)
    print(f"Wrote {len(records)} Threads to {out}")


if __name__ == "__main__":
    main()
