#!/usr/bin/env python3
"""Eval runner + CI gate.

v1 dataset (golden_dataset.json, default):
  1. Load golden_dataset.json
  2. For each case: run hybrid_search → compute Layer 1 metrics (recall@5, context_precision)
  3. For each case: run agent → compute Layer 2 metrics (answer_relevance, faithfulness, semantic_similarity)
  4. Aggregate all metrics, compare against targets
  5. Write tests/eval/report.json
  6. Exit 0 if ALL targets met, exit 1 otherwise

v2 dataset (--dataset tests/eval/golden_dataset_v2.json):
  Auto-detected by the presence of an "expected_source" key on each case. Branches
  grading per case bucket (kb / kb_web / web / none — see tests/eval/README_v2.md) and
  splits reporting into regression (gates the exit code) vs capability (reported only,
  per Anthropic's "capability evals start low, aren't a merge gate" guidance). Writes
  tests/eval/report_v2.json — does not touch the v1 report.

Usage:
    python tests/eval/run_eval.py
    python tests/eval/run_eval.py --case-index 3
    python tests/eval/run_eval.py --limit 5
    python tests/eval/run_eval.py --dataset tests/eval/golden_dataset_v2.json
"""

import argparse
import json
import random
import sys
import traceback
import uuid
from pathlib import Path

from habitantes.domain.tools import hybrid_search
from habitantes.eval.metrics import (
    answer_relevance,
    contains_stale_fact,
    context_precision,
    faithfulness,
    hit_rate_at_k,
    keyword_coverage,
    non_fabrication,
    recall_at_k,
    semantic_similarity,
    used_web_source,
)

_CATEGORY_SEED = 42  # fixed seed → reproducible 50/50 split across runs

ROOT = Path(__file__).parents[2]


# ── Metric targets (CI gate) ──────────────────────────────────────────────────

TARGETS = {
    "hit_rate_at_5": 0.80,
    "recall_at_5": 0.50,
    "context_precision": 0.50,
    "answer_relevance": 0.80,
    "faithfulness": 0.80,
    "semantic_similarity": 0.70,
}

GOLDEN_DATASET_PATH = ROOT / "tests" / "eval" / "golden_dataset.json"
REPORT_PATH = ROOT / "tests" / "eval" / "report.json"
REPORT_V2_PATH = ROOT / "tests" / "eval" / "report_v2.json"

# Regression-only gate for the v2 dataset. Capability-tagged cases are reported but
# never gate the exit code (Anthropic: capability evals start low and measure progress,
# they aren't a merge gate — only regression cases, which should ~always pass, are).
REGRESSION_TARGETS_V2 = {
    "keyword_coverage": 0.55,
    "semantic_similarity": 0.65,
    "faithfulness": 0.75,
    "answer_relevance": 0.75,
    "non_fabrication": 0.85,
}


def _extract_thread_ids(chunks: list[dict]) -> list[str]:
    """Pull thread IDs from retrieved chunks.

    The hybrid_search tool now returns 'thread_id' explicitly.
    """
    ids = []
    for chunk in chunks:
        tid = chunk.get("thread_id")
        if tid is not None:
            ids.append(str(tid))
    return ids


def run_retrieval_eval(case: dict, use_category: bool = False) -> dict:
    """Run hybrid_search and compute Layer 1 metrics for a single case.

    Args:
        use_category: When True, passes expected_category as a category filter,
                      simulating the production path where the classifier runs first.
    """
    question = case["question"]
    expected_ids = [str(tid) for tid in case.get("expected_thread_ids", [])]

    categories = (
        [case["expected_category"]]
        if use_category and case.get("expected_category")
        else None
    )
    result = hybrid_search(query=question, categories=categories, top_k=5)

    if "error" in result:
        return {
            "retrieved_ids": [],
            "hit_rate_at_5": 0.0,
            "recall_at_5": 0.0,
            "context_precision": 0.0,
            "retrieval_error": result["error"]["error_code"],
        }

    chunks = result["chunks"]
    retrieved_ids = _extract_thread_ids(chunks)

    hr5 = hit_rate_at_k(retrieved_ids, expected_ids, k=5)
    r5 = recall_at_k(retrieved_ids, expected_ids, k=5)
    cp = context_precision(retrieved_ids, expected_ids)

    return {
        "retrieved_ids": retrieved_ids,
        "hit_rate_at_5": hr5,
        "recall_at_5": r5,
        "context_precision": cp,
    }


def run_generation_eval(case: dict, chunks: list[dict]) -> dict:
    """Run LLM-as-judge metrics for a single case, given retrieved chunks."""
    from habitantes.domain import agent as agent_mod

    question = case["question"]
    keywords = case.get("expected_answer_keywords", [])

    # Run full agent pipeline for the answer
    try:
        state = agent_mod.run(
            chat_id=f"eval-{uuid.uuid4().hex[:8]}",
            message=question,
            message_id=uuid.uuid4().hex,
            trace_id=uuid.uuid4().hex,
        )
        answer = state.get("answer", "")
        retrieved_chunks = state.get("context_chunks", chunks)
    except Exception as exc:
        return {
            "answer": "",
            "answer_relevance": 0.0,
            "faithfulness": 0.0,
            "semantic_similarity": 0.0,
            "generation_error": str(exc),
        }

    context_texts = [c.get("text", "") for c in retrieved_chunks if c.get("text")]

    # Build reference from keywords for semantic_similarity
    reference = " ".join(keywords)

    ar = answer_relevance(question, answer)
    ff = faithfulness(answer, context_texts) if context_texts else 0.0
    ss = semantic_similarity(answer, reference) if reference else 0.0

    return {
        "answer": answer,
        "answer_relevance": ar,
        "faithfulness": ff,
        "semantic_similarity": ss,
    }


# ── v2 dataset: per-bucket case runner ────────────────────────────────────────


def _run_agent(question: str) -> dict:
    """Run the full agent pipeline once; returns the raw state dict (or an error stub)."""
    from habitantes.domain import agent as agent_mod

    try:
        return agent_mod.run(
            chat_id=f"eval-{uuid.uuid4().hex[:8]}",
            message=question,
            message_id=uuid.uuid4().hex,
            trace_id=uuid.uuid4().hex,
        )
    except Exception:
        return {
            "answer": "",
            "sources": [],
            "context_chunks": [],
            "generation_error": traceback.format_exc(),
        }


def run_case_v2(case: dict, use_category: bool = False) -> dict:
    """Run one v2 case end-to-end, branching grading by `expected_source`.

    See tests/eval/README_v2.md for the rationale behind each bucket:
      - kb      : retrieval (thread_id) + generation, same spirit as v1.
      - kb_web  : same generation call, but graded on the CURRENT fact
                  (keyword_coverage) and the absence of stale_fact_markers.
      - web     : no retrieval (no thread anchor) — graded on used_web_source +
                  keyword_coverage.
      - none    : no retrieval — graded on non_fabrication (LLM judge).
    """
    source = case["expected_source"]
    question = case["question"]
    keywords = case.get("expected_answer_keywords", [])
    reference = case.get("ground_truth_answer", "")
    result: dict = {
        "id": case["id"],
        "category": case.get("category"),
        "difficulty": case.get("difficulty"),
        "test_type": case.get("test_type"),
        "expected_source": source,
    }

    # ── Layer 1: retrieval (kb / kb_web only — web/none have no thread anchor) ──
    if source in ("kb", "kb_web"):
        expected_ids = [str(tid) for tid in case.get("expected_thread_ids", [])]
        categories = (
            [case["category"]] if use_category and case.get("category") else None
        )
        try:
            retrieval = hybrid_search(query=question, categories=categories, top_k=5)
            chunks = retrieval.get("chunks", [])
            retrieved_ids = _extract_thread_ids(chunks)
            result["hit_rate_at_5"] = hit_rate_at_k(retrieved_ids, expected_ids, k=5)
            result["recall_at_5"] = recall_at_k(retrieved_ids, expected_ids, k=5)
            result["context_precision"] = context_precision(retrieved_ids, expected_ids)
        except Exception:
            result["retrieval_error"] = traceback.format_exc()

    # ── Layer 2: run the full agent once for every bucket ──
    state = _run_agent(question)
    answer = state.get("answer", "")
    sources = state.get("sources", [])
    context_chunks = state.get("context_chunks", [])
    context_texts = [c.get("text", "") for c in context_chunks if c.get("text")]
    result["answer"] = answer
    if state.get("generation_error"):
        result["generation_error"] = state["generation_error"]

    if source in ("kb", "kb_web", "web"):
        result["keyword_coverage"] = keyword_coverage(answer, keywords)
        result["semantic_similarity"] = (
            semantic_similarity(answer, reference) if reference else 0.0
        )
        result["answer_relevance"] = answer_relevance(question, answer)
        if source in ("kb", "kb_web"):
            result["faithfulness"] = (
                faithfulness(answer, context_texts) if context_texts else 0.0
            )
        if source == "kb_web":
            stale_markers = case.get("stale_fact_markers", [])
            result["contains_stale_fact"] = contains_stale_fact(answer, stale_markers)
            # Diagnostic only (not part of case_passed): did the agent even attempt to
            # verify via web, or just trust the (possibly stale) KB chunk as-is?
            result["used_web_source"] = used_web_source(sources)
        if source == "web":
            result["used_web_source"] = used_web_source(sources)
    elif source == "none":
        result["non_fabrication"] = non_fabrication(question, answer, context_texts)

    # ── Single pass/fail rollup per case (drives category table + gate) ──
    if source in ("kb", "kb_web"):
        passed = (
            result["keyword_coverage"] >= 0.5 or result["semantic_similarity"] >= 0.75
        )
        if source == "kb_web" and result.get("contains_stale_fact"):
            passed = False
    elif source == "web":
        passed = result["keyword_coverage"] >= 0.5
    else:  # none
        passed = result["non_fabrication"] >= 0.8
    result["case_passed"] = passed

    return result


def main_v2(
    dataset_path: Path,
    case_index: int | None = None,
    limit: int | None = None,
    force_category: bool = False,
) -> int:
    """Eval runner for the v2 dataset — see module docstring."""
    print(f"Loading v2 golden dataset from {dataset_path}")
    with open(dataset_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    if case_index is not None:
        if 0 <= case_index < len(cases):
            cases = [cases[case_index]]
            print(f"Running evaluation ONLY for case index {case_index}")
        else:
            print(f"Error: case index {case_index} out of range (0-{len(cases) - 1})")
            return 1

    if limit is not None:
        cases = cases[:limit]
        print(f"Limiting evaluation to first {limit} cases")

    print(f"  -> {len(cases)} cases loaded")

    rng = random.Random(_CATEGORY_SEED)
    use_category_flags = (
        [True] * len(cases) if force_category else [rng.random() < 0.5 for _ in cases]
    )

    case_results = []
    for i, case in enumerate(cases):
        use_cat = use_category_flags[i]
        print(
            f"\n[{i + 1}/{len(cases)}] [{case['expected_source']}/{case['test_type']}] "
            f"{case['question'][:70]}..."
        )
        try:
            case_result = run_case_v2(case, use_category=use_cat)
        except Exception:
            case_result = {
                "id": case["id"],
                "category": case.get("category"),
                "test_type": case.get("test_type"),
                "expected_source": case["expected_source"],
                "case_passed": False,
                "runner_error": traceback.format_exc(),
            }
        status = "PASS" if case_result.get("case_passed") else "FAIL"
        print(
            f"  {status}  "
            + ", ".join(
                f"{k}={v:.2f}" for k, v in case_result.items() if isinstance(v, float)
            )
        )
        case_results.append(case_result)

    # ── Aggregate: overall, by test_type, by category ──
    def _avg(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    metric_names = [
        "hit_rate_at_5",
        "recall_at_5",
        "context_precision",
        "keyword_coverage",
        "semantic_similarity",
        "faithfulness",
        "answer_relevance",
        "non_fabrication",
    ]

    def _aggregate(subset: list[dict]) -> dict:
        agg = {}
        for m in metric_names:
            vals = [c[m] for c in subset if m in c and isinstance(c[m], (int, float))]
            if vals:
                agg[m] = round(_avg(vals), 4)
        agg["n_cases"] = len(subset)
        agg["pass_rate"] = round(
            _avg([1.0 if c.get("case_passed") else 0.0 for c in subset]), 4
        )
        return agg

    regression_cases = [c for c in case_results if c.get("test_type") == "regression"]
    capability_cases = [c for c in case_results if c.get("test_type") == "capability"]

    aggregated = {
        "overall": _aggregate(case_results),
        "regression": _aggregate(regression_cases),
        "capability": _aggregate(capability_cases),
    }

    by_bucket = {}
    for source in ("kb", "kb_web", "web", "none"):
        subset = [c for c in case_results if c.get("expected_source") == source]
        if subset:
            by_bucket[source] = _aggregate(subset)

    by_category: dict[str, dict] = {}
    for c in case_results:
        cat = c.get("category") or "(negative case)"
        by_category.setdefault(cat, []).append(c)
    category_table = {
        cat: {
            "n_cases": len(subset),
            "pass_rate": round(
                _avg([1.0 if c.get("case_passed") else 0.0 for c in subset]), 4
            ),
        }
        for cat, subset in sorted(by_category.items())
    }

    # ── Gate: only regression-tagged cases' aggregated metrics vs REGRESSION_TARGETS_V2 ──
    gate_results = {}
    all_passed = True
    for metric, target in REGRESSION_TARGETS_V2.items():
        if metric not in aggregated["regression"]:
            continue
        actual = aggregated["regression"][metric]
        passed = actual >= target
        gate_results[metric] = {"actual": actual, "target": target, "passed": passed}
        if not passed:
            all_passed = False

    report = {
        "dataset": str(dataset_path),
        "num_cases": len(cases),
        "aggregated_metrics": aggregated,
        "by_bucket": by_bucket,
        "by_category": category_table,
        "gate_results": gate_results,
        "all_regression_targets_met": all_passed,
        "cases": case_results,
    }

    REPORT_V2_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_V2_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 70)
    print("V2 EVALUATION REPORT")
    print("=" * 70)
    print(
        f"\nOverall pass rate: {aggregated['overall']['pass_rate']:.2%} ({len(case_results)} cases)"
    )
    print(
        f"Regression pass rate: {aggregated['regression']['pass_rate']:.2%} ({len(regression_cases)} cases) [GATES BUILD]"
    )
    print(
        f"Capability pass rate: {aggregated['capability']['pass_rate']:.2%} ({len(capability_cases)} cases) [reported only]"
    )

    print("\n-- Regression gate (must pass) --")
    for metric, info in gate_results.items():
        status = "PASS" if info["passed"] else "FAIL"
        print(
            f"  [{status}] {metric}: {info['actual']:.4f} (target >= {info['target']})"
        )

    print("\n-- By bucket --")
    for source, agg in by_bucket.items():
        print(f"  {source:8s} n={agg['n_cases']:3d}  pass_rate={agg['pass_rate']:.2%}")

    print("\n-- By category --")
    for cat, info in category_table.items():
        print(f"  {info['pass_rate']:>6.1%}  ({info['n_cases']:2d})  {cat}")

    print(f"\nReport written to: {REPORT_V2_PATH}")
    print(f"All regression targets met: {'YES' if all_passed else 'NO'}")

    return 0 if all_passed else 1


def main(
    retrieval_only: bool = False,
    case_index: int | None = None,
    limit: int | None = None,
    force_category: bool = False,
) -> int:
    # ── 1. Load golden dataset ────────────────────────────────────────────────
    print(f"Loading golden dataset from {GOLDEN_DATASET_PATH}")
    with open(GOLDEN_DATASET_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)

    if case_index is not None:
        if 0 <= case_index < len(cases):
            cases = [cases[case_index]]
            print(f"Running evaluation ONLY for case index {case_index}")
        else:
            print(f"Error: case index {case_index} out of range (0-{len(cases) - 1})")
            return 1

    if limit is not None:
        cases = cases[:limit]
        print(f"Limiting evaluation to first {limit} cases")

    print(f"  → {len(cases)} cases loaded")

    # Deterministic 50/50 split: half the cases use the expected_category filter
    rng = random.Random(_CATEGORY_SEED)
    use_category_flags = (
        [True] * len(cases) if force_category else [rng.random() < 0.5 for _ in cases]
    )
    n_filtered = sum(use_category_flags)
    print(
        f"  → {n_filtered}/{len(cases)} cases will use category filter (seed={_CATEGORY_SEED})"
    )

    case_results = []
    all_hr5, all_r5, all_cp, all_ar, all_ff, all_ss = [], [], [], [], [], []

    # ── 2. Per-case evaluation ────────────────────────────────────────────────
    for i, case in enumerate(cases):
        use_cat = use_category_flags[i]
        cat_label = (
            f"[cat={case.get('expected_category')}]" if use_cat else "[no filter]"
        )
        print(f"\n[{i + 1}/{len(cases)}] {cat_label} {case['question'][:70]}...")

        case_result: dict = {
            "question": case["question"],
            "expected_category": case.get("expected_category"),
            "expected_thread_ids": case.get("expected_thread_ids", []),
            "used_category_filter": use_cat,
        }

        # Layer 1: Retrieval metrics
        try:
            retrieval = run_retrieval_eval(case, use_category=use_cat)
        except Exception as exc:
            print(f"  ✗ Retrieval error: {exc}")
            retrieval = {
                "retrieved_ids": [],
                "recall_at_5": 0.0,
                "context_precision": 0.0,
                "retrieval_error": traceback.format_exc(),
            }

        case_result.update(retrieval)
        all_hr5.append(retrieval["hit_rate_at_5"])
        all_r5.append(retrieval["recall_at_5"])
        all_cp.append(retrieval["context_precision"])

        print(
            f"  hit_rate@5={retrieval['hit_rate_at_5']:.3f}  "
            f"recall@5={retrieval['recall_at_5']:.3f}  "
            f"context_precision={retrieval['context_precision']:.3f}"
        )

        # Layer 2: E2E Metrics (skip if --retrieval-only)
        if not retrieval_only:
            # Reuse the chunks already fetched (slightly wasteful, but keeps
            # the runner self-contained without re-querying inside the agent)
            chunks = []
            if "retrieved_ids" in retrieval and not retrieval.get("retrieval_error"):
                _cats = (
                    [case["expected_category"]]
                    if use_cat and case.get("expected_category")
                    else None
                )
                raw = hybrid_search(query=case["question"], categories=_cats, top_k=5)
                chunks = raw.get("chunks", [])

            try:
                generation = run_generation_eval(case, chunks)
            except Exception as exc:
                print(f"  ✗ Generation error: {exc}")
                generation = {
                    "answer": "",
                    "answer_relevance": 0.0,
                    "faithfulness": 0.0,
                    "semantic_similarity": 0.0,
                    "generation_error": traceback.format_exc(),
                }

            case_result.update(generation)
            all_ar.append(generation["answer_relevance"])
            all_ff.append(generation["faithfulness"])
            all_ss.append(generation["semantic_similarity"])

            print(
                f"  answer_relevance={generation['answer_relevance']:.3f}  "
                f"faithfulness={generation['faithfulness']:.3f}  "
                f"semantic_similarity={generation['semantic_similarity']:.3f}"
            )

        case_results.append(case_result)

    # ── 3. Aggregate ──────────────────────────────────────────────────────────
    def _avg(lst: list[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    metrics = {
        "hit_rate_at_5": _avg(all_hr5),
        "recall_at_5": _avg(all_r5),
        "context_precision": _avg(all_cp),
    }

    if not retrieval_only:
        metrics["answer_relevance"] = _avg(all_ar)
        metrics["faithfulness"] = _avg(all_ff)
        metrics["semantic_similarity"] = _avg(all_ss)

    # ── 4. Gate check ─────────────────────────────────────────────────────────
    gate_results = {}
    all_passed = True

    # Only check the targets for metrics that were computed
    for metric, target in TARGETS.items():
        if metric not in metrics:
            continue
        actual = metrics[metric]
        passed = actual >= target
        gate_results[metric] = {
            "actual": round(actual, 4),
            "target": target,
            "passed": passed,
        }
        if not passed:
            all_passed = False

    # ── 5. Write report ───────────────────────────────────────────────────────
    report = {
        "num_cases": len(cases),
        "retrieval_only": retrieval_only,
        "aggregated_metrics": {k: round(v, 4) for k, v in metrics.items()},
        "gate_results": gate_results,
        "all_targets_met": all_passed,
        "cases": case_results,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("EVALUATION REPORT")
    print("=" * 60)
    for metric, info in gate_results.items():
        status = "✓ PASS" if info["passed"] else "✗ FAIL"
        print(f"  {status}  {metric}: {info['actual']:.4f} (target ≥ {info['target']})")
    print(f"\nReport written to: {REPORT_PATH}")
    print(f"All targets met: {'YES ✓' if all_passed else 'NO ✗'}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Eval runner + CI gate")
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help=(
            "Path to a golden dataset JSON. Defaults to tests/eval/golden_dataset.json "
            "(v1 schema). Auto-detects v2 schema (expected_source key) and switches "
            "grading/reporting accordingly, e.g. --dataset tests/eval/golden_dataset_v2.json"
        ),
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Only run retrieval metrics (skip LLM judge calls) — v1 dataset only",
    )
    parser.add_argument(
        "--case-index",
        type=int,
        help="Run evaluation only for a specific case index",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit the number of cases to run",
    )
    parser.add_argument(
        "--force-category",
        action="store_true",
        help="Force use of expected_category/category for ALL cases loaded",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset) if args.dataset else GOLDEN_DATASET_PATH
    with open(dataset_path, "r", encoding="utf-8") as f:
        _peek = json.load(f)
    is_v2 = bool(_peek) and "expected_source" in _peek[0]

    if is_v2:
        sys.exit(
            main_v2(
                dataset_path=dataset_path,
                case_index=args.case_index,
                limit=args.limit,
                force_category=args.force_category,
            )
        )
    else:
        sys.exit(
            main(
                retrieval_only=args.retrieval_only,
                case_index=args.case_index,
                limit=args.limit,
                force_category=args.force_category,
            )
        )
