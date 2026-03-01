---
name: docs-writer
version: "1.0"
last_reviewed: "2025-01"
description: Write or edit documentation in docs/ and .specs/ for agentic/data science projects. Use when updating overview/architecture/contracts/evaluation or feature specs/design/tasks. Not for code implementation unless requested.
---

# Docs Writer (Lightweight)

## What “good docs” look like here
- Short sections, bullets, examples
- No duplicated truth: reference the standard/specs instead
- Contracts are copy/pasteable (JSON examples)
- Always include: non-goals + failure behavior + validation

## Workflow
1) Identify the doc goal (write new vs edit).
2) Read current file(s) before editing.
3) Make the smallest edit that matches the goal.
4) Ensure consistency across:
   - docs/overview.md (if present)
   - docs/architecture.md (if present)
   - docs/contracts.md (if present)
   - docs/evaluation.md (if present)
   - app/core/contracts.py (canonical contract source)
   - .specs/features/*

## Output format
- Files changed (list)
- What changed (bullets)
- Any follow-up docs needed
