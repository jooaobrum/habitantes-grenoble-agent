---
name: spec-driven-ds
version: "1.0"
last_reviewed: "2025-01"
description: Spec-driven delivery for DS/Agentic/GenAI using SPECIFY → DESIGN → TASKS → IMPLEMENT+VALIDATE, aligned with the Agent Systems Standard.
---

# Spec-Driven DS Skill

## Repo structure
.specs/
  project/
    STATE.md
    STATE.md
  features/
    <feature_slug>/
      spec.md
      design.md
      tasks.md

## Workflow
1) SPECIFY: write testable acceptance criteria (WHEN/THEN/SHALL) + non-goals.
2) DESIGN: minimal architecture (UI→API→Graph→Tools), typed state, offline ingestion, eval plan.
3) TASKS: atomic tasks with done-when checks.
4) IMPLEMENT+VALIDATE: implement tasks and validate against spec + eval gate.

## Guardrails
- Keep it simple: 1 orchestrator (graph) + a few tools.
- Required endpoints: POST /ask and POST /feedback.
- Never run ingestion/embedding at query time.
- If breaking changes: version contracts/state.

## Output format
- Specs updated list
- Atomic tasks (with done-when)
- Validation checklist (acceptance criteria + eval)


## Mandatory DS / GenAI requirements (must appear in SPECIFY)
When writing `spec.md`, always include these sections (even if brief):

1) **Data contracts**
   - inputs/outputs schema expectations
   - required fields, allowed ranges
   - missing/invalid handling (fail-fast vs fallback)

2) **Grounding & evidence**
   - what must come from tools/data (not the LLM)
   - evidence fields required in outputs (e.g., source, ids, scores)

3) **Safety & compliance**
   - refusal/escalation rules
   - sensitive data handling (masking/redaction) if applicable

4) **Quality metrics**
   - offline eval metric(s) + target thresholds
   - online/product metric(s) (feedback, adoption)

5) **Latency/cost budget**
   - target p50/p95 latency
   - tool call limits (max calls, timeouts)

6) **Failure modes + safe behavior**
   - ambiguity: ask 1 question OR provide 2 options with assumptions
   - no-results, tool failure, timeout
   - safe fallback behavior

7) **Observability**
   - trace_id
   - key events to log (tool failure, low confidence, fallback)

If any of these are missing, the spec is incomplete and must be updated before implementation.
