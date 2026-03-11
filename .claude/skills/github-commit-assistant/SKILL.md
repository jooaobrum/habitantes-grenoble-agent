---
description: Enforce minimal GitHub commit message standards using Conventional Commit-style prefixes. Use when user asks to organize commits, standardize history, improve readability, or prepare repository to evolve from MVP to production features.
name: github-commit-guidelines
---

# GitHub Commit Assistant

You are responsible for enforcing a **minimal, pragmatic commit convention** suitable for:

- Early MVP development
- Fast iteration
- Gradual evolution into structured features
- Clean, machine-readable history

This is not bureaucratic.
This is the **minimum acceptable discipline**.

---

# Core Philosophy

We build MVPs first.

Then we evolve them into features.

Commit history must reflect that evolution clearly.

---

# Mandatory Rule: Run Pre-Commit Before Any Commit

Before creating ANY commit, the developer MUST run:

pre-commit run --all-files

No commit is allowed if:

- Lint fails
- Formatting fails
- Tests (if configured in pre-commit) fail
- Static analysis fails

If pre-commit modifies files:

1. Stage changes again
2. Re-run pre-commit
3. Then commit

This guarantees:

- Clean formatting
- Consistent style
- Reduced review noise
- Stable foundation from MVP to production

---

# Commit Format (Mandatory)

All commits MUST follow:

<type>: short description

Optional (recommended later):

<type>(scope): short description

Examples:

feat: add basic authentication
fix: correct null pointer in loader
refactor: simplify inference pipeline
docs: update README
test: add unit tests for ranking
chore: update dependencies

---

# Allowed Types (Minimal Set)

Only these types are allowed:

- feat → new functionality
- fix → bug fix
- refactor → internal change without behavior change
- docs → documentation only
- test → tests only
- chore → maintenance / tooling
- perf → performance improvement

No custom types unless explicitly approved.

---

# Description Rules

- Lowercase
- Imperative mood ("add", not "added")
- No trailing period
- Max 72 characters
- Clear and direct

Good:
feat: add embedding pipeline

Bad:
Added new embedding pipeline functionality.

---

# MVP Phase Rule

During MVP phase:

- Small commits
- High frequency
- Clear intention
- Avoid giant mixed commits

If a commit does multiple things → split it.

---

# Feature Evolution Rule

When transitioning from MVP to structured feature:

- Use scope when helpful:

feat(auth): add jwt validation
fix(api): handle timeout error
refactor(ranking): isolate scoring logic

Scopes should be small and stable.

---

# What This Skill Does

When activated, you must:

1. Review recent commit messages
2. Suggest corrections
3. Rewrite non-compliant messages
4. Propose squash strategy if needed
5. Propose commit splitting if too large
6. Recommend cleanup before releases

---

# What This Skill Does NOT Do

- It does not enforce semantic versioning
- It does not require long commit bodies
- It does not introduce heavy GitFlow
- It does not create bureaucracy

---

# Enforcement Recommendation (Optional)

Minimal enforcement:

- Add commit-msg hook OR
- Add CI validation for commit message pattern:

^(feat|fix|refactor|docs|test|chore|perf)(\([a-z0-9\-]+\))?: .{1,72}$

---

# End Goal

Clean.
Readable.
Evolvable.

From MVP chaos → to production clarity.

Minimal structure.
Maximum velocity.
