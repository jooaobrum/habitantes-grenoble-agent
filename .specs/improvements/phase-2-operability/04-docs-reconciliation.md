# P2-04 · Reconcile docs with code as-built

**Phase:** 2 — Operability · **Priority:** P2 (do last, after P0/P1 change behavior) · **Audit:** §6, P2-8

## Problem
Docs describe a system never built or since changed, costing time for anyone working the repo.

| Docs claim | Reality |
|---|---|
| "LangGraph ReAct Agent", `MemoryState from langgraph` | Hand-rolled loop on `langchain_core` + plain dicts (keep code, fix docs). |
| Category Classifier LLM node | Only the numeric menu sets a category. |
| 8 categories (spec) | 19 bilingual in base.yaml. |
| `e5-small` (spec) / `e5-large` (base.yaml) / hardcoded loader | One model after P0-04. |
| Max 2 tool / 6 LLM calls per request (spec §5) | Up to 5 ReAct iterations × multiple tool calls. |
| design.md file map lists `nodes.py`, `prompts/category.py`, `api/pyproject.toml`, gitignored `report.json` | None exist / report.json is committed. |
| "5 years of WhatsApp knowledge" | Synthesis window starts 2024-02-15 → ~2 years (deliberate freshness). |

## Change
- One pass through README / OVERVIEW / ARCHITECTURE / spec.md / design.md to match the code as-built (favor code, not the docs).
- Update or delete stale [STATE.md](../../project/STATE.md) ("Next steps: T1.1").
- Align spec's tool/LLM-call limits with actual `max_react_iterations`, or cap in code to match spec.

## Done when
- [ ] No doc references LangGraph, a category-classifier node, `nodes.py`, or `prompts/category.py`.
- [ ] Category count, embedding model, and KB time window match the code/config.
- [ ] STATE.md reflects reality or is removed.
