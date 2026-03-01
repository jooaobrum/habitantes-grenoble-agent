---
name: coding-guidelines
version: "1.0"
last_reviewed: "2025-01"
description: Apply when writing/modifying/reviewing code in this repo (agent systems, tools, ingestion, evaluation). Enforces simplicity-first, surgical changes, verifiable goals, and standard boundaries (UI/API/Graph/Tools/Ingestion). Not for product brainstorming.
---

# Coding Guidelines (Testing Phase)

## 1) Think before coding
- State assumptions. If uncertain, ask 1 question.
- If simpler approach exists, prefer it.
- Disagree if the plan is wrong (avoid sycophancy).

## 2) Simplicity first
- Minimum code that solves the requested problem.
- No speculative flexibility.
- No abstractions for single-use code.

## 3) Surgical changes
- Touch only what the request needs.
- Don’t refactor adjacent code unless required.
- Remove only the dead code you introduced.

## 4) Goal-driven execution — always verify

Every task ends with verification. “Done” means verified, not just written.

Turn tasks into checks before writing code:
- “Add validation” → write failing test → make it pass → run `python tests/eval/run_eval.py`
- “Fix bug” → reproduce with test → fix → run `python tests/eval/run_eval.py`
- “Add a node” → add eval case for new behavior → implement → run `python tests/eval/run_eval.py`

**Verified means:** `python tests/eval/run_eval.py` passes AND `pytest tests/ -v` passes.
If verification fails: fix it. Do not say done with a failing gate.
Use `prompts/verify.prompt.md` as the checklist for the full loop.

## 5) Agent-system constraints (must follow)
From `docs/standard/agent-systems-standard.md`:
- UI never imports agent logic
- Orchestration explicit, tools thin
- Ingestion offline, not at query time
- Typed stable contracts/state
