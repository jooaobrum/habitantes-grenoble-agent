# MVP Tasks

## Phase 1: Project Skeleton & Config

- [x] **T1.1 — Bootstrap project structure**
  Create `api/src/habitantes/` tree, `app/`, `tests/`, `pyproject.toml`, `Makefile`, `docker-compose.yml`, `.env.example`.
  **Done when:** directory tree matches `design.md` file map, `make lint` runs.

- [x] **T1.2 — Configuration module**
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

## Phase 3: RAG Pipeline Evaluation

- [ ] **T3.1 — Create golden dataset**
  `tests/eval/golden_dataset.json` — 20+ evaluation cases covering ≥ 10 categories, including 2+ no-results cases. Each case: `{question, expected_category, expected_doc_ids, expected_answer_keywords}`.
  **Done when:** `golden_dataset.json` is valid JSON; `len(cases) >= 20`; ≥ 10 categories covered; ≥ 2 no-results cases.

- [ ] **T3.2 — Implement retrieval metrics**
  `api/src/habitantes/eval/metrics.py` — pure functions: `recall_at_k(retrieved, relevant, k)`, `context_precision(retrieved, relevant)`. No LLM needed.
  **Done when:** `pytest tests/unit/test_metrics.py` passes; no real services needed.

- [ ] **T3.3 — Implement E2E metrics**
  `api/src/habitantes/eval/metrics.py` — LLM-as-judge functions: `answer_relevance(question, answer)`, `faithfulness(answer, context)`, `semantic_similarity(answer, reference)`. Uses OpenAI direct call (not LangChain).
  **Done when:** LLM judge mocked in unit tests; all 5 metric functions exist in `metrics.py`.

- [ ] **T3.4 — Eval runner + report + CI gate**
  `tests/eval/run_eval.py` — loads golden dataset, runs retrieval + generation pipeline, computes all metrics, writes `tests/eval/report.json`, exits 0 if all targets met, exits 1 otherwise.
  **Done when:** `python tests/eval/run_eval.py` exits 0; `report.json` written with all metric scores.

## Phase 4: Infrastructure Layer

- [ ] **T4.1 — FastAPI service**
  `infrastructure/api/main.py` + routers: `POST /chat`, `POST /feedback`, `GET /health`. Rate limiting (100 req/user/hr). `trace_id` on every request. Structured errors.
  **Done when:** all endpoints return correct responses, rate limiting works, integration tested.

- [ ] **T4.2 — Telegram Bot**
  `app/telegram_bot.py` — long-polling bot using `python-telegram-bot`. Calls `/chat` over HTTP. Per-chat locks, message deduplication, typing indicator.
  **Done when:** bot responds in Telegram, tested manually with real messages.

## Phase 5: Deployment & Verification

- [ ] **T5.1 — Docker setup**
  `docker-compose.yml` (api + qdrant + telegram-bot), Dockerfiles for api and bot.
  **Done when:** `docker compose up` starts all 3 services, `/health` returns 200.

- [ ] **T5.2 — Final verification**
  End-to-end smoke test: Telegram → API → Graph → Qdrant → response. Confirm eval gate passes.
  **Done when:** `pytest tests/ -v` passes, `python tests/eval/run_eval.py` exits 0.
