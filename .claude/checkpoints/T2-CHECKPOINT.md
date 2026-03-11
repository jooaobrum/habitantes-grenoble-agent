# T2 Checkpoint — habitantes-grenoble-agent

**Date:** 2026-03-01
**Branch:** `dev` (ahead of `main`, not yet merged)
**Tests:** 104 passing (`pytest tests/ -q`)
**Status:** T2.1–T2.5 fully implemented, committed and pushed to `dev`.

---

## What was done in T2

All domain layer tasks completed. The agent graph is fully wired and tested.

### Commits on dev (T2 work)
```
9652459 chore(claude): update skill metadata
6292830 test(integration): multi-turn conversation tests and smoke test
3fa016b feat(domain): categories as config source of truth with number selection
d96f779 fix(config): load .env via dotenv, optional telegram, embedding e5-large (1024d)
02ab196 feat(domain): implement nodes, hybrid search tool and agent graph (T2.3-T2.5)
84049a4 feat(domain): implement intent classifier and synthesis prompts (T2.2)
3023511 feat(domain): implement AgentState TypedDict and Pydantic schemas (T2.1)
```

---

## Architecture (current)

```
UI → API → LangGraph Graph → Tools (hybrid_search)
              ↑
          AgentState (TypedDict)
Ingestion ──┘ (offline, Qdrant)
```

**Graph flow:**
```
classify_intent
    ├── greeting      → generate_greeting
    ├── out_of_scope  → generate_decline
    ├── feedback      → log_feedback
    ├── rag           → search → generate_answer
    └── clarify       → generate_clarification
```

**Key shortcut:** if message is a digit (1–19), `classify_intent` bypasses the LLM entirely, resolves the category from config, and routes to `clarify`.

---

## Key files

| File | Role |
|------|------|
| `api/src/habitantes/domain/state.py` | `AgentState` TypedDict |
| `api/src/habitantes/domain/schemas.py` | Pydantic API contracts |
| `api/src/habitantes/domain/agent.py` | LangGraph graph + `run()` + `_memory` |
| `api/src/habitantes/domain/nodes.py` | All graph nodes |
| `api/src/habitantes/domain/tools.py` | `hybrid_search` (dense+sparse+RRF+rerank) |
| `api/src/habitantes/domain/categories.py` | Pure helpers: `resolve_number`, `build_greeting_text`, `get_by_en_name` |
| `api/src/habitantes/domain/prompts/intent.py` | `build_intent_messages()` |
| `api/src/habitantes/domain/prompts/synthesis.py` | `build_synthesis_messages()` |
| `api/src/habitantes/config.py` | `Settings`, `CategoryEntry`, `load_settings()` |
| `config/base.yaml` | Single source of truth for categories (19 entries) + LLM/Qdrant config |
| `smoke_test.py` | Manual E2E test — 9 scenarios A–I |
| `tests/unit/test_*.py` | 4 unit test files |
| `tests/integration/test_agent_flow.py` | 13 integration tests |
| `tests/integration/test_conversations.py` | 5 multi-turn conversation tests |

---

## Memory structure

```python
_memory: dict[str, dict] = {}
# _memory[chat_id] = {"messages": [...], "category": "Visa & Residency"}
```

- `category` persists across turns until user picks a new number or sends a greeting.
- Greeting resets category to `""`.
- `_MAX_HISTORY` caps the message list.

---

## Category system

- 19 categories in `config/base.yaml` as `{pt_name, en_name}`.
- User types a number (1–19) → mapped to `CategoryEntry` → `en_name` stored in memory and passed to Qdrant filter.
- PT name shown to user in greeting menu and clarification response.
- EN name used as `categories` filter kwarg in `hybrid_search(...)`.

---

## Tool contract

```python
# Success
{"chunks": [{"text", "question", "answer", "source", "date", "category", "score"}, ...]}

# Failure
{"error": {"error_code": "QDRANT_UNREACHABLE", "message": "...", "retryable": True}}
```

Error codes: `EMBEDDING_FAILURE`, `QDRANT_TIMEOUT`, `QDRANT_UNREACHABLE`.

---

## Config / secrets

- `config/base.yaml` — base config (embedding model, Qdrant URL, categories, etc.)
- `.env` — secrets (`OPENAI_API_KEY`, etc.). Loaded via `load_dotenv()` inside `load_settings()`.
- `TELEGRAM_BOT_TOKEN` is optional (`default=""`). Not needed for domain layer.
- Embedding model: `intfloat/multilingual-e5-large` → **1024 dimensions** (matches ingestion pipeline).

---

## Test layout

```
tests/
├── unit/
│   ├── test_config.py        (4)
│   ├── test_schemas.py       (13)
│   ├── test_prompts.py       (12)
│   ├── test_nodes.py         (19)
│   ├── test_categories.py    (11)
│   └── test_tools.py         (25)
└── integration/
    ├── test_agent_flow.py    (13)
    └── test_conversations.py  (5)
                           ─────
                           102 + 2 (number-selection tests in agent_flow)
                           = 104 total
```

All LLM and Qdrant calls mocked. No real services needed to run `pytest`.

---

## Smoke test (manual)

```bash
# Full run (requires real OpenAI + Qdrant)
QDRANT_URL=http://localhost:6333 python smoke_test.py

# Single scenario by name substring
QDRANT_URL=http://localhost:6333 python smoke_test.py "number"
```

Scenarios: A Greeting, B Direct question, C Number→question, D Greeting→number→question,
E Category switch, F Out-of-scope, G Feedback, H Short message, I Greeting resets category.

---

## What is NOT done yet (next tasks)

- `T3.*` — FastAPI infrastructure layer (`api/src/habitantes/infrastructure/api/main.py`)
- Docker Compose wiring (api + Qdrant)
- UI (`app/`) calling the API over HTTP
- Eval gate (`tests/eval/run_eval.py`)
- Merge `dev` → `main` via PR (requires Tech Lead approval)

---

## How to resume

```bash
# 1. Activate venv
source .venv/bin/activate

# 2. Confirm tests green
pytest tests/ -q

# 3. Check what's next
cat .specs/features/mvp/tasks.md

# 4. Read design
cat .specs/features/mvp/design.md
```
