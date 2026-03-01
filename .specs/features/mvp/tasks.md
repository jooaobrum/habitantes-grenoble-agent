# MVP Tasks

## Phase 1: Project Skeleton & Config

- [x] **T1.1 — Bootstrap project structure**
  Create `api/src/habitantes/` tree, `app/`, `tests/`, `pyproject.toml`, `Makefile`, `docker-compose.yml`, `.env.example`.
  **Done when:** directory tree matches `design.md` file map, `make lint` runs.

- [ ] **T1.2 — Configuration module**
  `api/src/habitantes/config.py` — Pydantic Settings from `.env`. Settings: `openai_api_key`, `qdrant_url`, `telegram_token`, `model_name`, `collection_name`, `embedding_model`, `rate_limit_per_hour`.
  **Done when:** `config.py` loads all settings, import works, test passes.

## Phase 2: Domain Layer

- [x] **T2.1 — State & schemas**
  `domain/state.py` — `AgentState` TypedDict per design.md.
  `domain/schemas.py` — `ChatRequest`, `ChatResponse`, `FeedbackRequest`, `Source`, `HealthResponse`.
  **Done when:** all types importable, Pydantic validation works, tests pass.

- [x] **T2.2 — Prompts**
  `domain/prompts/intent.py` — intent classification prompt (greeting/qa/feedback/out_of_scope).
  `domain/prompts/category.py` — category classification prompt (8 categories).
  `domain/prompts/synthesis.py` — answer synthesis prompt (Portuguese, grounded, with sources).
  **Done when:** all prompts render correctly with sample data.

- [x] **T2.3 — Nodes**
  `domain/nodes.py` — pure functions: `classify_intent`, `classify_category`, `route`, `generate_response`, `generate_greeting`, `generate_decline`, `generate_clarification`, `log_feedback`.
  **Done when:** each node tested with mocked LLM, returns correct state updates.

- [x] **T2.4 — Tools (hybrid search)**
  `domain/tools.py` — `hybrid_search` thin wrapper: embeds query (dense + sparse), queries Qdrant, returns `{chunks: [...]}` or `{error: {...}}`. Lazy model loading via factory.
  **Done when:** tool returns typed results with mock Qdrant, error path tested.

- [x] **T2.5 — Agent graph**
  `domain/agent.py` — LangGraph `StateGraph` wiring all nodes + tools per design.md graph. In-memory short-term memory (last 5 msgs per chat_id).
  **Done when:** graph compiles, full happy-path flow works with mocked tools/LLM.

## Phase 3: Infrastructure Layer

- [ ] **T3.1 — FastAPI service**
  `infrastructure/api/main.py` + routers: `POST /chat`, `POST /feedback`, `GET /health`. Rate limiting (100 req/user/hr). `trace_id` on every request. Structured errors.
  **Done when:** all endpoints return correct responses, rate limiting works, integration tested.

- [ ] **T3.2 — Telegram Bot**
  `app/telegram_bot.py` — long-polling bot using `python-telegram-bot`. Calls `/chat` over HTTP. Per-chat locks, message deduplication, typing indicator.
  **Done when:** bot responds in Telegram, tested manually with real messages.

## Phase 4: Deployment & Verification

- [ ] **T4.1 — Docker setup**
  `docker-compose.yml` (api + qdrant + telegram-bot), Dockerfiles for api and bot.
  **Done when:** `docker compose up` starts all 3 services, `/health` returns 200.

- [ ] **T4.2 — Eval & testing**
  Unit tests (nodes, tools, schemas). Integration test (full graph). 5+ eval cases. `run_eval.py`.
  **Done when:** `pytest tests/ -v` passes, `python tests/eval/run_eval.py` passes.
