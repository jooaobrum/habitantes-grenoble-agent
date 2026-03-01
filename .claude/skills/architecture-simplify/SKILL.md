---
name: architecture-simplify
version: "1.0"
last_reviewed: "2025-01"
description: Simplify architecture; enforce Agent Systems Standard boundaries; remove overengineering.
---

# Architecture Simplify Skill

## Checklist
- Keep only: UI → API → Graph (Orchestration) → Tools (+ typed State)
- Ingestion is offline and independent
- Tools are thin wrappers (no orchestration)
- API contracts stable; required endpoints exist

## Deliverables
- Simplified architecture diagram (text)
- 3–5 do/don’t rules
- Delete/avoid list
