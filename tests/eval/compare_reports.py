#!/usr/bin/env python3
"""Compare a baseline and a feature v2 eval report (issue #59, Suggestions).

Pass rates use the existing per-case rule (`case_passed` in each report case, written
by run_eval.run_case_v2). Cases are assigned to suites ("recommendation",
"v1_regression") through the dataset's `suite` tag, joined by case id, so reports made
before the tag existed (e.g. checkpoints/report_v2.v0.baseline.json) still work.

Success is recorded as: recommendation pass rate improves (strictly) AND regression
pass rate does not drop. Only cases present in BOTH reports count, so a baseline taken
on a partial or older dataset is compared like with like. A suite with no common cases
makes the verdict a failure (nothing was measured).

Usage:
    python tests/eval/compare_reports.py BASELINE.json FEATURE.json \\
        [--dataset tests/eval/golden_dataset_v2.json] [--out comparison.json]

Exit code 0 on success, 1 on failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
DEFAULT_DATASET = ROOT / "tests" / "eval" / "golden_dataset_v2.json"
DEFAULT_OUT = ROOT / "tests" / "eval" / "suggestions_comparison.json"

RECOMMENDATION_SUITE = "recommendation"
REGRESSION_SUITE = "v1_regression"


def suites_by_id(dataset: list[dict]) -> dict[str, str]:
    return {c["id"]: c["suite"] for c in dataset if c.get("suite")}


def _passed_by_id(report: dict) -> dict[str, bool]:
    return {c["id"]: bool(c.get("case_passed")) for c in report.get("cases", [])}


def _rate(passed: list[bool]) -> float | None:
    return round(sum(passed) / len(passed), 4) if passed else None


def suite_stats(
    baseline: dict, feature: dict, suite_of: dict[str, str], suite: str
) -> dict:
    base, feat = _passed_by_id(baseline), _passed_by_id(feature)
    ids = sorted(
        i for i, s in suite_of.items() if s == suite and i in base and i in feat
    )
    return {
        "n_cases": len(ids),
        "baseline_pass_rate": _rate([base[i] for i in ids]),
        "feature_pass_rate": _rate([feat[i] for i in ids]),
        "fixed": [i for i in ids if feat[i] and not base[i]],
        "broken": [i for i in ids if base[i] and not feat[i]],
        "still_failing": [i for i in ids if not base[i] and not feat[i]],
    }


def compare(baseline: dict, feature: dict, dataset: list[dict]) -> dict:
    suite_of = suites_by_id(dataset)
    rec = suite_stats(baseline, feature, suite_of, RECOMMENDATION_SUITE)
    reg = suite_stats(baseline, feature, suite_of, REGRESSION_SUITE)

    measured = rec["n_cases"] > 0 and reg["n_cases"] > 0
    rec_improved = measured and rec["feature_pass_rate"] > rec["baseline_pass_rate"]
    reg_held = measured and reg["feature_pass_rate"] >= reg["baseline_pass_rate"]
    reasons = []
    if not measured:
        reasons.append("a suite has no cases common to both reports")
    else:
        if not rec_improved:
            reasons.append("recommendation pass rate did not improve")
        if not reg_held:
            reasons.append("regression pass rate dropped")
    return {
        "recommendation": rec,
        "regression": reg,
        "recommendation_improved": rec_improved,
        "regression_not_dropped": reg_held,
        "success": rec_improved and reg_held,
        "failure_reasons": reasons,
    }


def _fmt(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate:.1%}"


def render(result: dict) -> str:
    lines = ["Suggestions evaluation: baseline vs feature", ""]
    for key, label in (
        ("recommendation", "Recommendation"),
        ("regression", "Regression"),
    ):
        s = result[key]
        lines.append(
            f"{label:15s} n={s['n_cases']:3d}  baseline={_fmt(s['baseline_pass_rate'])}"
            f"  feature={_fmt(s['feature_pass_rate'])}"
            f"  fixed={len(s['fixed'])}  broken={len(s['broken'])}"
        )
        if s["broken"]:
            lines.append(f"  broken: {', '.join(s['broken'])}")
    lines.append("")
    if result["success"]:
        lines.append(
            "SUCCESS: recommendation pass rate improved and regression did not drop."
        )
    else:
        lines.append("FAILURE: " + "; ".join(result["failure_reasons"]) + ".")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("baseline", type=Path)
    parser.add_argument("feature", type=Path)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))  # noqa: E731
    result = compare(load(args.baseline), load(args.feature), load(args.dataset))
    result["baseline_report"] = str(args.baseline)
    result["feature_report"] = str(args.feature)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(render(result))
    print(f"\nComparison written to: {args.out}")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
