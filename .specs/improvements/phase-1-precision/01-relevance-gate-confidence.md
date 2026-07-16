# P1-01 · Relevance gate + real confidence from cosine

**Phase:** 1 — Precision · **Priority:** P0 (the core ask) · **Audit:** P0-1

## Problem
No relevance threshold exists anywhere. Fused scores in [search.py:119-150](../../../api/src/habitantes/domain/tools/search.py) are RRF rank sums (max ≈ 0.016), encoding *rank* not *relevance*. [agent.py:339-345](../../../api/src/habitantes/domain/agent.py) sets `confidence = min(1.0, top_score)` → every QA answer ships at ~0.01, and nothing refuses to answer an off-topic question. The spec ([spec.md §2 Grounding](../../features/mvp/spec.md)) requires returning the fallback when top similarity is below threshold.

## Change
- In `hybrid_search`, preserve the real dense cosine similarity per chunk as `dense_score` (currently overwritten at [search.py:149-150](../../../api/src/habitantes/domain/tools/search.py)). Keep RRF for **ordering only**.
- Add `search.min_relevance` to [base.yaml](../../../config/base.yaml) + `SearchConfig`. Tune on the golden set (e5 question-question similarity for true matches typically ≥ 0.85).
- In the agent, before synthesis: drop chunks below a per-chunk floor; if `max(dense_score) < min_relevance` → return the fallback string **without an LLM synthesis call**.
- Set `confidence = top dense_score`.

## Done when
- [x] Out-of-KB question ("melhor pizzaria de Paris?") → exact fallback, no synthesis call, low confidence.
- [x] Answerable question → grounded answer, `confidence` == top dense similarity (not ~0.01).
- [x] Threshold lives in `base.yaml` (`search.min_relevance` = 0.85), not hardcoded.
- [x] `make eval` still green. Tuned on the 38-case golden set (lowest true-positive
      top dense = 0.8774 → 0.85 gates zero true matches). All 6 targets pass:
      hit_rate@5 0.974, recall@5 0.616, context_precision 0.543, answer_relevance
      0.947, faithfulness 0.826, semantic_similarity 0.916.

## Do not
- Do not add a cross-encoder reranker (tasks.md T6.9) — hit_rate@5 is already 0.97; the gap is policy, not ranking.
