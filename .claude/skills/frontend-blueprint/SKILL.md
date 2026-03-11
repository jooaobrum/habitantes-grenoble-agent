---
name: frontend-blueprint
version: "1.0"
last_reviewed: "2025-01"
description: Plan a minimal frontend for an agentic/DS app (forms, dashboards, validation UI) that calls backend APIs. Use when asked to build or improve a UI, define inputs, or translate a workflow into screens. Not for backend architecture or database design.
---

# Frontend Blueprint (DS / Agentic)

## Core rule
UI collects inputs + renders outputs. No business logic. No agent logic imports.

## Quick discovery (ask only what’s necessary)
- Primary user + top task
- One golden path: input → expected output
- Output type: text answer? ranked list? table? chart?
- Constraints: latency target, auth, where hosted

## Design decisions (minimal)
- Prefer **one screen** for MVP.
- States: idle → loading → result | empty | error
- Result rendering:
  - Answer (markdown)
  - Confidence (0–1)
  - Evidence (compact list)
  - Trace link (optional)
  - Feedback widget (rating + comment → POST /feedback)

## API contract to align with
- POST /ask
- POST /feedback
Use the schemas in `app/core/contracts.py` as baseline.

## Output format
- UI input model (fields + validation + defaults)
- Screen layout (wireframe in bullets)
- Component list (minimal)
- API request/response examples
- UX risks + mitigations
