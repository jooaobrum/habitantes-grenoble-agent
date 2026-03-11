---
name: agent-system-architect
version: "1.0"
last_reviewed: "2025-01"
description: Design or review an agent system architecture for data science / GenAI projects. Use when starting a new agent project, defining repo structure, adding orchestration/tools/ingestion, or reviewing boundaries. Enforces UI→API→Graph→Tools + typed State, offline ingestion, stable contracts, and minimal endpoints (/ask,/feedback). Not for UI styling details or code-only refactors.
---

# Agent System Architect (DS / GenAI)

## Non-negotiables (enforce)
Read `docs/standard/agent-systems-standard.md` and enforce:
- Agents are services (not notebooks)
- Explicit orchestration (graph/workflow/state machine)
- UI never imports agent logic
- Ingestion offline and separate from inference
- Typed, stable state + API contracts
- Tools are thin wrappers (no orchestration logic)
- Layers must be replaceable independently

## Workflow (lightweight)
1) **Discovery (5–10 min)**
   - What is the user outcome? (1–2 sentences)
   - Golden path input/output (1 example)
   - Top 3 failure modes
   - Latency/cost target (chatbot)

2) **Architecture (decide before coding)**
   - Confirm boundaries: UI → API → Graph → Tools (+ typed State), Ingestion offline
   - List tools (2–5 max for MVP) with one-line responsibilities
   - Define state fields (minimum needed)
   - Define contracts for:
     - POST /ask
     - POST /feedback
   - Define ingestion outputs: stable chunk IDs + manifest/versioning

3) **Spec tie-in**
   - Ensure `.specs/features/<feature>/spec.md` has testable acceptance criteria
   - Ensure `.specs/features/<feature>/design.md` matches the architecture

4) **Validate**
   - Identify any rule violations + how to fix
   - Identify overengineering to remove

## Output format (mandatory)
- Architecture diagram (text)
- Components + responsibilities (bullets)
- Contracts to create/update (bullets)
- MVP tool list + state schema outline
- Risks + mitigations (top 3)
- “Remove/avoid” list (anti-overengineering)
