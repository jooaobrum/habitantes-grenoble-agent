---
name: config-driven-settings
version: "1.0"
last_reviewed: "2025-01"
description: Build config-driven projects using YAML + Pydantic Settings + environment selection. Generates config/*.yaml, .env templates, Pydantic config models, and a loader that selects config by APP_ENV. Use when starting a new project, adding new config keys, or refactoring hardcoded constants. Not for designing business logic or complex config frameworks.
---

# Config-Driven Settings (YAML + Pydantic) — Lightweight

## Goals
- Keep configuration **typed**, **validated**, and **environment-specific**
- Support `dev`, `qa`, `prod` with minimal duplication
- Keep secrets out of Git: `.env` + env vars + container secrets

## Minimal pattern (recommended)
- `config/base.yaml` — non-secret defaults shared across envs
- `config/dev.yaml`, `config/prod.yaml` — env overrides (small)
- `.env` — local developer secrets + APP_ENV
- `app/core/settings.py` — Pydantic models + loader

### Precedence (simple)
1) Environment variables (.env locally)
2) Env YAML override (dev/prod/qa)
3) base.yaml defaults

## Inputs you need
- List of configuration domains (API, LLM, DB, Vector store, UI, Logging, Ingestion)
- Which values are secrets (tokens, passwords, private keys)
If not provided, produce a sensible DS/agentic default.

## What to generate (deliverables)
1) `config/base.yaml`, `config/dev.yaml`, `config/prod.yaml`
2) `.env.example` (safe template) and `.env` (local, gitignored)
3) `app/core/settings.py`:
   - Pydantic models (nested per domain)
   - `load_settings()` selecting env via `APP_ENV`
4) Optional: docs update (only if contracts depend on config keys)

## Pydantic guidance
- Use `pydantic-settings` for env loading + validation.
- Keep models small: one nested model per domain (`ApiConfig`, `LlmConfig`, ...).
- Default to `APP_ENV=dev`.
- Cache settings object (`@lru_cache`) for FastAPI deps.

## Output format (mandatory)
Return:
- Files created/updated
- YAML keys added/changed (bullets)
- Pydantic model fields added/changed
- How to run (APP_ENV + example env vars)
