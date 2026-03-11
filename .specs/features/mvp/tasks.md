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

- [x] **T3.1 — Create golden dataset**
  `tests/eval/golden_dataset.json` — 20+ evaluation cases covering ≥ 10 categories, including 2+ no-results cases. Each case: `{question, expected_category, expected_thread_ids, expected_answer_keywords}`.
  **Done when:** `golden_dataset.json` is valid JSON; `len(cases) >= 20`; ≥ 10 categories covered; ≥ 2 no-results cases.

- [x] **T3.2 — Implement retrieval metrics**
  `api/src/habitantes/eval/metrics.py` — pure functions: `recall_at_k(retrieved, relevant, k)`, `context_precision(retrieved, relevant)`. No LLM needed.
  **Done when:** `pytest tests/unit/test_metrics.py` passes; no real services needed.

- [x] **T3.3 — Implement E2E metrics**
  `api/src/habitantes/eval/metrics.py` — LLM-as-judge functions: `answer_relevance(question, answer)`, `faithfulness(answer, context)`, `semantic_similarity(answer, reference)`. Uses OpenAI direct call (not LangChain).
  **Done when:** LLM judge mocked in unit tests; all 5 metric functions exist in `metrics.py`.

- [x] **T3.4 — Eval runner + report + CI gate**
  `tests/eval/run_eval.py` — loads golden dataset, runs retrieval + generation pipeline, computes all metrics, writes `tests/eval/report.json`, exits 0 if all targets met, exits 1 otherwise.
  **Done when:** `python tests/eval/run_eval.py` exits 0; `report.json` written with all metric scores.

- [x] **T3.5 — Improved Hybrid Search (FastEmbed BM25)**
  Update `ingestion/3-build_qdrant_collection.py` and `api/src/habitantes/domain/tools.py` to use `fastembed` for sparse vectors (BM25, Portuguese). Synchronize normalization and glossary enrichment between ingestion and retrieval. Create `tests/retrieval_smoke_test.py`.
  **Done when:** `hybrid_search` uses `fastembed`, retrieval smoke test passes, `run_eval.py` shows improved metrics.

## Phase 4: Infrastructure Layer

- [x] **T4.1 — FastAPI service**
  `infrastructure/api/main.py` + routers: `POST /chat`, `POST /feedback`, `GET /health`. Rate limiting (100 req/user/hr). `trace_id` on every request. Structured errors.
  **Done when:** all endpoints return correct responses, rate limiting works, integration tested.

- [x] **T4.2 — Telegram Bot**
  `app/telegram_bot.py` — long-polling bot using `python-telegram-bot`. Calls `/chat` over HTTP. Per-chat locks, message deduplication, typing indicator.
  **Done when:** bot responds in Telegram, tested manually with real messages.

## Phase 5: Deployment & Verification

- [x] **T5.1 — Docker setup**
  `docker-compose.yml` (api + qdrant + telegram-bot), Dockerfiles for api and bot.
  **Done when:** `docker compose up` starts all 3 services, `/health` returns 200.

- [x] **T5.2 — Final verification**
  End-to-end smoke test: Telegram → API → Graph → Qdrant → response. Confirm eval gate passes.
  **Done when:** `pytest tests/ -v` passes, `python tests/eval/run_eval.py` exits 0.

## Phase 6: MVP Hardening

- [x] **T6.1 — Clean package boundaries**
  - Rewrite `api/src/habitantes/domain/tools/__init__.py` (4 specific public exports).
  - Move `domain/glossary.py` → `domain/tools/glossary.py` (update imports).
  - Fix consumer imports: `health.py:3`, `test_tools.py:12-18`, `_ranking.py:80`.
  - Fix `pyproject.toml` → use `[tool.setuptools.packages.find]` with `where = ["api/src"]`.
  - Delete `fix_tests.py` — dead migration script.
  **Done when:** `tools/` is self-contained with 4 exports only, `pytest tests/ -v` passes.

- [x] **T6.2 — Centralize all hardcoded constants in config**
  - Add `search`, `ranking`, and `agent` sections to `config/base.yaml`.
  - Add `SearchConfig`, `RankingConfig`, `AgentConfig` to `config.py`.
  - Update `search.py`, `_ranking.py`, and `agent.py` to use `settings.*` instead of hardcoded globals.
  - Fix `tests/unit/test_config.py` to cover new sections.
  **Done when:** zero hardcoded tuning constants remain in domain code; `base.yaml` is the single source of truth.

- [x] **T6.3 — Cost protection & anti-spam hardening**
  - Add `max_tokens_per_response`, `request_timeout_seconds` to `ApiConfig`.
  - Add `rate_limit_per_minute`, `max_message_length` to `TelegramConfig`.
  - Set `max_tokens` on `ChatOpenAI` in `agent.py`.
  - Add rate limiting + size validation (2000 chars) to Telegram bot.
  - Implement TTL cleanup for `_processed_messages` and `_rate_limits` to prevent memory leaks.
  - Use `settings.api.rate_limit_per_hour` in FastAPI middleware.
  **Done when:** Spam and oversized messages are rejected politely; OpenAI bill risk is capped.

- [x] **T6.4 — Simple response cache for repeated questions**
  - Create `domain/cache.py` with in-memory TTL+LRU cache (keyed by normalized query + category).
  - Integrate into `agent.py`: check cache before LLM/search, store valid results after.
  - Add `cache` section to `base.yaml` (enabled, max_size, ttl_seconds).
  - Add `CacheConfig` to `config.py`.
  - Write `tests/unit/test_cache.py`.
  **Done when:** repeated questions return cached results instantly; `cached: true` in response.

- [x] **T6.5 Restructure ingestion pipeline**
    - [x] Refactor scripts into `ingestion/` package.
    - [x] Centralize ingestion configs in `base.yaml`.
    - [x] Implement orchestrator `pipeline.py`.
  - Create `ingestion/run.py` CLI entry point.
  - Refactor scripts 0-3 into modules within the package stages.
  - Delete old numbered scripts.
  **Done when:** `python -m ingestion.run all` runs the full pipeline successfully.

## Phase 6.5: Bug Fixes & Retrieval Improvement

- [x] **T6.6 — Fix CacheConfig missing fields**
  `api/src/habitantes/config.py` — `CacheConfig` only has `ttl_seconds`, but `base.yaml` and `cache.py` expect `enabled` and `max_size`. Causes `AttributeError` at runtime.
  - Add `enabled: bool = True` and `max_size: int = 256` to `CacheConfig`.
  - Update `tests/unit/test_config.py` to cover new fields.
  **Done when:** `load_settings().cache.enabled` works; `pytest tests/unit/test_config.py` passes.

- [x] **T6.7 — Fix double search in agent**
  `api/src/habitantes/domain/agent.py` — `_track_chunks()` re-calls `hybrid_search` after the tool already searched in the ReAct loop. Redundant latency.
  - Capture chunks from the tool result directly instead of re-searching.
  **Done when:** only 1 search call per QA turn; `pytest tests/ -v` passes.

- [x] **T6.8 — Fix Telegram source formatting**
  `app/telegram_bot.py` — `s.get('category' or 'Geral')` uses wrong operator precedence; fallback never triggers.
  - Fix to `s.get('category') or 'Geral'` (same for `date`).
  **Done when:** sources display correctly with fallback when fields are missing.

- [ ] **T6.9 — Cross-encoder reranking**
  Add cross-encoder model (`cross-encoder/ms-marco-MiniLM-L-6-v2`) to re-score top-N candidates after RRF fusion, before final top-k selection. Runs locally, no API cost. Expected: 67% retrieval error reduction.
  - `domain/tools/_ranking.py` — add `rerank_with_cross_encoder()` step.
  - `config/base.yaml` — add `ranking.reranker_model`, `ranking.reranker_top_n`.
  - `config.py` — add fields to `RankingConfig`.
  **Done when:** reranking active; `python tests/eval/run_eval.py` exits 0.

- [ ] **T6.10 — Re-evaluate and update report**
  Run full eval suite after all fixes + reranking. Save updated `tests/eval/report.json`.
  - Document metric deltas (recall@5, context_precision, hit_rate@5, answer_relevance).
  **Done when:** `report.json` updated; all gates pass; metric comparison documented.

- [x] **T6.11 — Deep-dive retrieval tools**
  Implement `list_knowledge_subcategories` and `get_chunks_by_category` tools to help the agent explore specific topics when standard search is insufficient. Update system prompt to use them.
  **Done when:** tools added to agent; verification test passes; evaluation shows better handling of edge cases.

## Phase 7: CI/CD & Deployment

- [ ] **T7.1 — CI/CD pipeline**
  Set up GitHub Actions workflow to run lint, tests, build Docker images, and push to a container registry on each push.
  CI:
    lint/tests
    image build
    registry push
    tagged release

  CD:
    SSH deploy from CI
    pull and restart services
    smoke test
    rollback



- [ ] **T7.2 — Deploy to VPS**
  Create deployment scripts that pull the latest images on the VPS and run `make up ENV = X`.
  Integrate CI to trigger deployment on successful builds.

  - [ ] **T7.3 — Add monitoring**
  Create simple monitoring for:
  Docker
  containers
  disk usage
  CPU
  memory
  network
  health
