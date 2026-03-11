---
name: subagent-creator
version: "1.0"
last_reviewed: "2025-01"
description: Create or refine subagents for GitHub Copilot/VS Code (.github/agents/*.agent.md). Use when adding a specialized assistant (reviewer/verifier/debugger/frontend/architect) that needs isolated context. Not for adding normal skills (SKILL.md) or writing business logic.
---

# Subagent Creator (Lightweight)

## Decide: Skill or Subagent
- Use a **Skill** when: reusable procedure + no isolated context needed.
- Use a **Subagent** when: complex workflow, verification/auditing, or long context that should not pollute the main thread.

## Subagent file format (Copilot / VS Code)
Create: `.github/agents/<name>.agent.md`

Frontmatter:
- `name`: Title Case (human-readable)
- `description`: **trigger phrases** and when to use (critical)
- `tools`: keep minimal
Optional:
- `readonly: true` for reviewer/verifier style agents

Body:
- Mission
- Responsibilities
- Output format (structured, short)

## Creation steps
1) Name (kebab-case filename), clear scope.
2) Write description with:
   - “Use when …”
   - Example trigger phrases users/devs will say
   - “Not for …” if overlap risk exists
3) Define output format (bullets/checklists), not essays.
4) Add 2 example invocations.

## Templates (copy/paste)
### Reviewer / Verifier
- readonly: true
- Output: PASS/FAIL checks + actionable fixes

### Builder (Frontend/Tooling)
- readonly: false
- Output: files to create + minimal steps


## Rule: Prefer skills over domain agents
- Do NOT create domain-specific custom agents (e.g., "maintenance-agent.agent.md").
- Instead, create **skills** for domain workflows and keep subagents as generic tech roles (architect, backend, QA, frontend).
- Reason: skills load on-demand (less context, less maintenance) and compose better.
