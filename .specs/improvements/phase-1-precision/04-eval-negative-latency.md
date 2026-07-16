# P1-04 · Eval: negative cases + fallback_accuracy + latency

**Phase:** 1 — Precision · **Priority:** P0 · **Audit:** P2-1, P2-2

## Problem
All 38 golden cases are answerable, so the no-threshold problem (P1-01) is structurally invisible to the gate — the eval cannot see a regression in precision. Eval also measures no latency despite the p95 < 5 s spec target. Judges hardcode `gpt-4o-mini` ([metrics.py:133,168](../../../api/src/habitantes/eval/metrics.py)), which CLAUDE.md forbids.

## Change
- Add ~8–10 **negative** cases to [golden_dataset.json](../../../tests/eval/golden_dataset.json): out-of-KB questions expecting the exact fallback string, and out_of_scope ones expecting a decline.
- Add a `fallback_accuracy` metric (fraction of negative cases correctly answered with the fallback/decline) to the gate in [run_eval.py](../../../tests/eval/run_eval.py).
- Capture per-case wall time; report p50/p95 in the report.
- Read the judge model from settings instead of hardcoding.

## Done when
- [ ] Golden set contains negative cases with a distinguishing field (e.g. `expects_fallback: true`).
- [ ] `fallback_accuracy` is computed and gated.
- [ ] Report includes p50/p95 latency.
- [ ] Judges use `settings.llm.model_name`.
- [ ] `make eval` green including the new metric.
