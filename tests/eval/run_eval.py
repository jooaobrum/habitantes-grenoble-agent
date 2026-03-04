#!/usr/bin/env python3
"""Eval runner + CI gate.

Steps:
  1. Load golden_dataset.json
  2. For each case: run hybrid_search → compute Layer 1 metrics (recall@5, context_precision)
  3. For each case: run agent → compute Layer 2 metrics (answer_relevance, faithfulness, semantic_similarity)
  4. Aggregate all metrics, compare against targets
  5. Write tests/eval/report.json
  6. Exit 0 if ALL targets met, exit 1 otherwise

Usage:
    python tests/eval/run_eval.py
    python tests/eval/run_eval.py --retrieval-only   # skip LLM judge (faster)
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
    context_precision,
    faithfulness,
    hit_rate_at_k,
    recall_at_k,
    semantic_similarity,
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


def main(retrieval_only: bool = False) -> int:
    # ── 1. Load golden dataset ────────────────────────────────────────────────
    print(f"Loading golden dataset from {GOLDEN_DATASET_PATH}")
    with open(GOLDEN_DATASET_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)
    print(f"  → {len(cases)} cases loaded")

    # Deterministic 50/50 split: half the cases use the expected_category filter
    rng = random.Random(_CATEGORY_SEED)
    use_category_flags = [rng.random() < 0.5 for _ in cases]
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
        "--retrieval-only",
        action="store_true",
        help="Only run retrieval metrics (skip LLM judge calls)",
    )
    args = parser.parse_args()
    sys.exit(main(retrieval_only=args.retrieval_only))
