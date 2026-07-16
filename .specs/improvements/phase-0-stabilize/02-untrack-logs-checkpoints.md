# P0-02 · Untrack committed logs + checkpoints

**Phase:** 0 — Stabilize · **Priority:** P0 · **Audit:** P1-6, P2-6

## Problem
[api/logs/interactions.jsonl](../../../api/logs/interactions.jsonl) — a real interaction log containing actual `chat_id`s and user queries — is committed to git. `.claude/checkpoints/` and `.claude/SUGGESTIONS.md` are tracked despite being gitignored.

## Change
- `git rm --cached api/logs/interactions.jsonl .claude/checkpoints/*.md .claude/SUGGESTIONS.md`.
- Add `api/logs/` and `logs/` to [.gitignore](../../../.gitignore).
- Keep the runtime log directory creation ([logging.py](../../../api/src/habitantes/infrastructure/logging.py)) — only the committed file is removed.

## Done when
- [ ] `git ls-files | grep -E "interactions.jsonl|checkpoints/|SUGGESTIONS"` returns nothing.
- [ ] `git status` clean after the removals are committed.
- [ ] Runtime still writes logs locally (untracked).
