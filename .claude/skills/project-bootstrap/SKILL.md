---
name: project-bootstrap
version: "1.0"
last_reviewed: "2025-01"
description: Create initial specs and project docs from the ideation brief, aligned with the Agent Systems Standard.
---

# Project Bootstrap Skill

## Required input format

`docs/ideation/ideation-brief.md` must be filled before running this skill. It must contain at minimum:
- Problem statement (1–2 sentences)
- Target users (primary + secondary)
- Golden path example (one input → expected output)
- Data sources
- Success criteria (quality metric + latency target)
- Out-of-scope items for MVP
- Top 3 risks
- Failure modes table

See the template at `docs/ideation/ideation-brief.md` and the filled example at `docs/examples/doc-qa-agent/ideation-brief.md`.

If the ideation brief is missing or incomplete, stop and ask the user to fill it first.

## Inputs
- `docs/ideation/ideation-brief.md` (human-written)
- `docs/standard/agent-systems-standard.md` (rules)

## Steps
1) Create/update `.specs/project/STATE.md` (decisions, blockers, next steps).
2) Create MVP feature spec folder `.specs/features/mvp/`:
   - `spec.md` (WHEN/THEN/SHALL acceptance criteria)
   - `design.md` (UI→API→Graph→Tools + State + Ingestion)
   - `tasks.md` (atomic tasks with done-when checks)
3) Refresh docs:
   - `docs/overview.md`
   - `docs/architecture.md`
   - `docs/evaluation.md`
   Note: API contracts live in `app/core/contracts.py` — keep docs in sync with it.
4) Propose 10–20 initial eval cases.

## Output
- Specs created/updated
- MVP plan (vertical slice)
- Initial eval set outline
- Top risks + mitigations
