#!/usr/bin/env python3
"""Run only specified case IDs from golden_dataset_v2.json, without the 67-case cost.

Reuses run_case_v2 from the real runner (same grading logic) — this is purely a
faster feedback loop for prompt iteration, not a replacement for the full gate run.

Usage:
    python tests/eval/checkpoints/run_isolated.py bank-kbweb-01 travel-kbweb-01
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT / "tests" / "eval"))
sys.path.insert(0, str(ROOT / "api" / "src"))

from run_eval import run_case_v2  # noqa: E402

DATASET_PATH = ROOT / "tests" / "eval" / "golden_dataset_v2.json"


def main() -> None:
    ids = sys.argv[1:]
    if not ids:
        print("Usage: run_isolated.py <case-id> [<case-id> ...]")
        sys.exit(1)

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        all_cases = {c["id"]: c for c in json.load(f)}

    missing = [i for i in ids if i not in all_cases]
    if missing:
        print(f"Unknown case ids: {missing}")
        sys.exit(1)

    results = []
    for cid in ids:
        case = all_cases[cid]
        print(f"\n{'=' * 80}\n{cid}  [{case['expected_source']}/{case['test_type']}]")
        print(f"Q: {case['question']}")
        result = run_case_v2(case, use_category=False)
        results.append(result)
        status = "PASS" if result.get("case_passed") else "FAIL"
        print(f"-> {status}")
        for k, v in result.items():
            if isinstance(v, (float, bool)):
                print(f"   {k} = {v}")
        print(f"   answer: {result.get('answer', '')[:400]}")

    n_pass = sum(1 for r in results if r.get("case_passed"))
    print(f"\n{'=' * 80}\n{n_pass}/{len(results)} passed")


if __name__ == "__main__":
    main()
