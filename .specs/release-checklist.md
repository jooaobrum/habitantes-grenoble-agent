# Release Checklist

> Use this before merging any non-trivial feature or before first user-facing release.
> All items must be checked. If an item cannot be checked, it must be explicitly waived with a reason.

---

## 1. Spec completeness

- [ ] `spec.md` exists and has all 7 mandatory DS/GenAI sections:
  - [ ] Data contracts (input/output schema + validation)
  - [ ] Grounding & evidence (what must come from tools, not LLM)
  - [ ] Safety & compliance (refusal rules, PII handling)
  - [ ] Quality metrics (offline + online, with targets)
  - [ ] Latency/cost budget (p50, p95, max tool calls)
  - [ ] Failure modes + safe behaviors
  - [ ] Observability (trace_id, key log events)
- [ ] `design.md` matches `spec.md` (graph, state, tools, contracts)
- [ ] `tasks.md` has "done when" for every task

---

## 2. Reviews

- [ ] **Tech Architect:** APPROVED (boundaries, contracts, state stability)
- [ ] **Design:** APPROVED (UI minimal, no business logic, API usage correct)
- [ ] **Tech Lead:** APPROVED (plan adherence, scope, anti-overengineering)

> Optional (for changes affecting eval coverage):
> - [ ] **Eval Engineer:** APPROVED (grounding, coverage, thresholds)

---

## 3. Eval gate

- [ ] Eval cases exist in `tests/eval/cases/` for this feature
- [ ] `python tests/eval/run_eval.py` passes (no gates failed)
- [ ] No regression on existing eval cases
- [ ] Every new behavior has ≥ 1 eval case

---

## 4. Engineering

- [ ] Contracts/state are stable (no breaking changes) — OR versioned if breaking
- [ ] Safe fallbacks exist for all failure modes in `spec.md`
- [ ] Structured errors used at tool/API boundaries
- [ ] `trace_id` is propagated through the full request lifecycle
- [ ] Key log events are emitted (tool_failure, fallback_triggered, etc.)

---

## 5. Config & deployment

- [ ] No hardcoded model names, thresholds, or API keys in code
- [ ] `config/base.yaml` (and env overrides) are up to date
- [ ] `docker compose up` starts all services cleanly
- [ ] `GET /healthz` returns 200

---

## Waived items

| Item | Reason | Approved by |
|---|---|---|
| | | |
