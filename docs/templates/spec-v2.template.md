# <MVP / Feature Name> — SPECIFY (WHAT)

## Problem statement
(1–3 sentences)

## Scope
**In:**
- …

**Out:**
- …

## Users & workflow (golden path)
User:
System:

## Acceptance criteria (WHEN / THEN / SHALL)
1) WHEN … THEN system SHALL …
2) WHEN … THEN system SHALL …

## Mandatory DS / GenAI requirements

### 1) Data contracts
- Inputs:
- Outputs:
- Validation rules:
- Missing/invalid handling:

### 2) Grounding & evidence (anti-hallucination)
- Facts that MUST come from tools/data:
- Evidence fields required in outputs (ids, sources, scores):

### 3) Safety & compliance
- Refusal / escalation rules:
- Sensitive data handling (if applicable):

### 4) Quality metrics
- Offline metric(s) + target:
- Online metric(s) + target:

### 5) Latency/cost budget
- Latency targets (p50/p95):
- Max tool calls:
- Timeouts:

### 6) Failure modes + safe behavior
- Ambiguity behavior:
- No-results behavior:
- Tool failure/timeout behavior:

### 7) Observability
- trace_id requirement:
- logs/metrics (minimum):

## Non-goals
- …

## Assumptions
- …
