---
name: prompt-editor
version: "1.1"
last_reviewed: "2025-01"
description: Edit and improve an existing prompt/template (system/user/tool prompt) while preserving intent and variables. Use when asked to rewrite/clean/clarify a prompt, reduce ambiguity, improve structure, or make it easier to evaluate. Not for changing product requirements or adding new features.
---

# Prompt Editor (Lightweight)

## When to use
- "Improve this prompt"
- "Make the prompt clearer / more objective"
- "Refactor this template but keep variables"
- "Add structure so it's easier to test/evaluate"
- "Make tool instructions clearer"

## Goals (in order)
1. **Preserve intent** (no hidden requirement changes)
2. **Improve clarity & objectiveness** (remove vague language)
3. **Improve structure** (sections, ordering, scannability)
4. **Preserve variables** (do not rename/remove unless asked)
5. **Make it testable** (inputs/outputs + acceptance checks)

## Input you need (minimal)
- The current prompt/template
- Any known failure modes (optional)
- Target output format (optional)

If missing, proceed with reasonable defaults and state assumptions.

## Best practices to apply

**Use prompt templates with named variables** for dynamic content (e.g. `{{user_query}}`). Keep variable names stable — renaming them is a breaking change for callers.

**Use a consistent section structure:**
- Purpose
- Inputs
- Constraints / guardrails
- Steps (if multi-step)
- Output format
- Examples (only if they materially help)

**Wrap variable content in XML tags** for clarity when the prompt contains multiple context pieces (e.g. `<context>...</context>`, `<retrieved_chunks>...</retrieved_chunks>`). This improves parsing reliability.

**Keep instructions targeted.** Avoid blanket defaults like "always be helpful" — prefer specific constraints like "answer only from the provided chunks."

**For tool-use prompts, specify explicitly:**
- When to call the tool (and when not to)
- What each parameter means
- What to do when the tool returns an error or empty result

**Make evaluation easy:** include acceptance criteria or a short "pass/fail checklist" at the end of the prompt doc.

## Default prompt structure (template)

```
## Purpose
[1–2 sentences: what this prompt achieves]

## Inputs
- {{variable_name}}: [description]

## Constraints
- [Do X]
- [Never do Y]

## Process
1. [Step 1]
2. [Step 2]

## Output format
[Describe expected structure, e.g. JSON schema or markdown sections]

## Examples
[Only include if behavior is non-obvious]
```

## Output format (mandatory)
Return:
1. **Rewritten prompt** (ready to paste)
2. **Change log** (bullets: what changed, why)
3. **Test suggestions** (3–8 representative inputs + what "good" looks like)
