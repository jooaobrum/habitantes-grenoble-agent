# Chatbot Agent Habitantes de Grenoble

## Architecture rules (never break these)

```
UI → API → Graph (LangGraph) → Tools
                ↑
              State (TypedDict)
Ingestion ────┘  (offline only, never at query time)
```

**Layer rules:**
- UI never imports agent logic — UI calls API only
- Graph nodes never import infrastructure directly — always go through tools
- Tools are thin wrappers — no decisions, no orchestration logic
- State is a TypedDict passed through the graph — no global mutable state
- Every request gets a `trace_id`
- Errors are structured: `{error_code, message, retryable}`

**SOLID principles — apply always:**
- **S** — each module has one reason to change. Nodes do routing/logic. Tools do I/O. Contracts define the boundary. Never mix.
- **O** — add new LLM providers or vector stores by adding a new tool, not by modifying existing ones.
- **L** — any tool that satisfies the same return contract (`{"chunks": [...]}` or `{"error": {...}}`) is interchangeable.
- **I** — keep tool interfaces narrow. `vector_store.retrieve(query)` does one thing only.
- **D** — graph nodes depend on tool *interfaces* (the dict contract), not on specific implementations (ChromaDB, AzureOpenAI).

See `.claude/skills/python-patterns/SKILL.md` for the design patterns used in this codebase.

## How to work in this repo

1. Start from `docs/ideation/ideation-brief.md` (human-written)
2. Use `project-bootstrap` + `spec-driven-ds` to generate `.specs/`
3. Implement **one task at a time** from `tasks.md`
4. Verify after every task: `python tests/eval/run_eval.py` must pass
5. Review before merging (Tech Architect → Design → Tech Lead)

## Verify before done

Never say "done" without running:
```bash
python tests/eval/run_eval.py
pytest tests/ -v
```
If either fails: fix it first.

## Core Rules (Non-Negotiable)

1. Agents are **SERVICES**, not notebooks.
2. Orchestration is **EXPLICIT** (graph/workflow/state machine).
3. UI **NEVER** imports agent logic directly.
4. Ingestion is **separate** from inference.
5. State and API contracts must be **typed and stable**.
6. Tools are **thin wrappers**, not decision-makers.
7. Every layer must be **replaceable independently**.

If any change violates these rules, the design is wrong.

## Ingestion Rules

- Never embed at query time.
- Use stable chunk IDs.
- Track document versions (manifest).
- Keep ingestion idempotent.
- Store metadata necessary for filtering and traceability.


## Plan before implementing

For any non-trivial task: list the files you'll touch and what you'll change. Wait for confirmation. Then implement.

## Command language

- **SPECIFY** — write/update `spec.md` (what the system does)
- **PLAN** — write/update `design.md` (how it's built)
- **TASKS** — generate/update `tasks.md` (atomic tasks with done-when)
- **IMPLEMENT** — implement one task only
- **VALIDATE** — run reviews + eval gate

## Reviewers

- **Tech Architect** — boundaries, contracts, state changes
- **Design** — UI changes, API contract usage
- **Tech Lead** — final approval before every merge
- **Eval Engineer** — eval coverage, grounding, safety thresholds

All reviews: **Agent + Decision (APPROVE | REQUEST_CHANGES) + Reason**

## Avoid

- Multiple tasks in one session
- Hardcoded model names, thresholds, API keys (use `settings`)
- Logic in UI, logic in tools
- Generating answers when retrieval returns empty results
- Changing spec to match broken code

## What we learned


### Copilot mistakes (AI behaviour to correct)

- **Don’t use `print()` for debugging** → use `logger.debug()` with `trace_id`
- **Don’t hardcode model names** → always use `settings.llm.model`
- **Don’t catch bare `except:`** → catch specific exceptions, return `ToolError`
- **Don’t change `contracts.py` without updating eval cases** → they must stay in sync
- **Don’t generate an answer when `chunks` is empty** → return the no-results fallback
- **Don’t add state fields without updating `state.py` TypedDict** → state drift breaks the graph


## Skills vs custom agents

**Default: prefer skills.** Load on demand, reusable, no extra maintenance.
Create a custom agent (`.claude/agents/`) only for reviewer roles that need consistent decision ownership.

## Reference

- Example project: `docs/examples/doc-qa-agent/`
- Skills: `.claude/skills/SKILLS.md`
- Release gate: `.specs/release-checklist.md`


## Current Stack

- **Framework:** LangGraph
- **LLM:** OpenAI
- **Vector Store:** Qdrant (docker)
- **UI:** HTML, CSS , JS
- **API:** FastAPI
- **State Management:** TypedDict
- **Testing:** pytest


```
habitantes-grenoble-agent/│
├── README.md
├── Makefile                         # make run, make test, make lint
├── docker-compose.yml               # api + app + infra services
├── .env.example
├── .gitignore
├── pyproject.toml
│
│
├── notebooks/                       # PARALLEL EXPERIMENTATION — DS always
│   ├── requirements.txt             # Can be heavier than api deps
│   ├── 01_data_exploration/
│   ├── 02_agent_experiments/        # Trying new approaches not yet in api/
│   ├── 03_evaluation/               # Measuring quality of what's in api/
│   └── data/                        # Local test data (gitignored if large)
│
│
├── api/                             # DS builds MVP here. Devs industrialize here.
│   ├── Dockerfile
│   ├── Makefile
│   │
│   └── src/
│       └── {package_name}/
│           ├── __init__.py
│           ├── config.py            # Pydantic Settings — reads .env
│           │
│           │
│           ├── domain/              # ← DS WRITES THIS DURING MVP
│           │   │                   #   Pure logic. No HTTP, no DB clients, no framework I/O.
│           │   │                   #   Devs touch this only to refactor, not rewrite.
│           │   ├── __init__.py
│           │   ├── agent.py         # Agent graph (LangGraph StateGraph, etc.)
│           │   ├── nodes.py         # Individual agent nodes
│           │   ├── tools.py         # Tool definitions
│           │   ├── schemas.py       # Domain Pydantic models (input/output contracts)
│           │   ├── prompts/
│           │   │   └── system.py
│           │   └── memory/
│           │       ├── short_term.py
│           │       └── long_term.py
│           │
│           │
│           ├── infrastructure/
│           │   ├── __init__.py
│           │   │
│           │   ├── api/             # ← DS WRITES THIS DURING MVP (minimal)
│           │   │   ├── main.py      #   FastAPI app + routes in one file is fine for MVP
│           │   │   ├── routers/     #   ← Devs split into routers during industrialization
│           │   │   │   ├── chat.py
│           │   │   │   └── health.py
│           │   │   └── models.py    #   HTTP request/response models
│           │   │
│           │   ├── db/              # ← Devs extract from domain during industrialization
│           │   │   ├── vector_store.py
│           │   │   └── relational.py
│           │   │
│           │   ├── llm_providers/   # ← Devs extract from domain during industrialization
│           │   │   └── groq.py
│           │   │
│           │   └── monitoring/      # ← Devs add during industrialization
│           │       └── tracer.py
│           │
│           │
│           └── application/         # ← Devs add during industrialization
│               │                   #   Not needed for MVP. DS calls domain directly from api/.
│               ├── __init__.py
│               ├── chat_service.py
│               ├── ingest_service.py
│               └── evaluation_service.py
│
│
├── app/                             # DS builds MVP here. Devs harden or replace.
│   ├── Dockerfile
│   ├── README.md
│   │
│   │   # MVP (DS): Single Streamlit or Gradio script
│   ├── main.py                      # DS writes this — calls api/ over HTTP
│   ├── requirements.txt
│   │
│   │   # Prod (Devs, optional): Full JS frontend
│   │   # If devs replace with Next.js/React, they add:
│   │   # ├── package.json
│   │   # ├── src/
│   │   # └── public/
│
│
└── .claude/
    └── workflows/
        ├── ci-api.yml               # Lint + unit tests for api/ — active from MVP
        └── ci-app.yml               # Active from industrialization
```
