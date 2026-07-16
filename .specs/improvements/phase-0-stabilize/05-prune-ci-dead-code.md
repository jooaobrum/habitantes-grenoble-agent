# P0-05 · Prune CI to lint+tests; delete dead code/config/dep

**Phase:** 0 — Stabilize · **Priority:** P1 · **Audit:** P1-5, P2-4

## Problem
[ci.yml](../../../.github/workflows/ci.yml) installs a nonexistent `api/requirements.txt`, runs `make` targets needing uv (not installed in CI), and ends with Docker-push + SSH-deploy steps pointing at `/path/to/deployment/directory` — it has never passed. Separately, dead artifacts exist: `eval_gate_enabled` (defined, env-mapped, unit-tested, never read), the `langgraph` dependency (zero imports, verified), and `_get_collection_name()` in [_embedding.py:15-21](../../../api/src/habitantes/domain/tools/_embedding.py) (references an undefined global; would NameError; never called).

## Change
- Rewrite CI to: checkout → setup-uv → `uv sync --group dev` → lint (pre-commit) → `pytest tests/unit api/tests`. Remove Docker-push and SSH-deploy stanzas until deployment is actually automated.
- Delete `eval_gate_enabled` (config field, env mapping, and its test assertion) — or wire it to actually gate; deletion is simpler.
- Remove `langgraph` from [pyproject.toml](../../../pyproject.toml) dependencies.
- Delete the dead `_get_collection_name()` in `_embedding.py`.
- Keep `make eval` documented as a **local** pre-merge gate (needs Qdrant + OpenAI + artifacts; not a CI step).

## Done when
- [ ] CI job is green on a PR (lint + unit tests only).
- [ ] `grep -r eval_gate_enabled` and `grep -r langgraph` (code) return nothing.
- [ ] Unit suite still passes after deletions.
