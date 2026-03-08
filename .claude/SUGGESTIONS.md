# Suggestions for .claude Sanitization

**Purpose:** Patterns found in the codebase + lessons from T1–T2 sessions that are not
yet captured in existing rules, skills, or conventions. Use this as a backlog
for the weekly sanitization sprint.

Each item includes: what it is, where it lives today, and what action to take.

---

## 1. New Skills to Create

These are patterns that appear consistently in the codebase but have no
dedicated skill or template yet.

---

### 1.1 `langgraph-agent` skill

**What:** The full skeleton for building a LangGraph `StateGraph` agent — including
`AgentState` TypedDict, node wiring, `_route_intent()` conditional dispatch,
`_memory` in-process session store, `run()` entry point, and compile-at-import pattern.

**Where today:**
- `api/src/habitantes/domain/agent.py` — graph wiring + memory
- `api/src/habitantes/domain/nodes.py` — node structure
- `api/src/habitantes/domain/state.py` — AgentState

**Why a skill:** Every new agent project starts by reproducing this exact skeleton.
Without a skill, it gets copied and drifts. The skill should contain:
- `AgentState` TypedDict skeleton with required fields
- `StateGraph` wiring skeleton (nodes + conditional edges + END)
- `_route_intent()` dispatcher pattern
- `_memory` dict + `_get_history()` / `_update_memory()` helpers
- `run()` public entry point pattern

**Action:** Create `.claude/skills/langgraph-agent/SKILL.md` + `templates/agent.py`

---

### 1.2 `qdrant-hybrid-search` skill

**What:** The hybrid search pattern: dense (sentence-transformers) + sparse (BM25 hashing)
→ Qdrant RRF prefetch → anchor rerank. Includes the tool contract shape, lazy client
factories, and constants that must match the ingestion pipeline.

**Where today:** `api/src/habitantes/domain/tools.py`

**Why a skill:** This is the most complex tool in the stack. New contributors will
reproduce it wrong (wrong vector names, wrong sparse dim, wrong prefetch K values).
The skill should contain:
- The exact `_SPARSE_DIM`, `_DENSE_VECTOR`, `_SPARSE_VECTOR` constant block
- The 3 lazy factories (`_get_dense_model`, `_get_qdrant_client`, `_get_collection_name`)
- The RRF prefetch + rerank query pattern
- The `{"chunks": [...]}` / `{"error": {...}}` contract reminder

**Action:** Create `.claude/skills/qdrant-hybrid-search/SKILL.md` + `templates/tool.py`

---

### 1.3 `monkeypatch-llm` skill (testing pattern)

**What:** The pattern for mocking LLM calls in pytest without real API keys:
`_make_llm(*responses)` → `monkeypatch.setattr(nodes_module, "_get_llm", lambda: llm)` +
`monkeypatch.setattr(nodes_module, "_llm", None)`.
Also covers: patching `hybrid_search`, patching `_get_collection_name`,
and using `autouse` fixtures to reset `_memory` and `_categories_cache`.

**Where today:**
- `tests/integration/test_agent_flow.py` — helpers + fixtures
- `tests/integration/test_conversations.py` — multi-turn pattern
- `tests/unit/test_nodes.py` — `_make_state()` helper

**Why a skill:** Every test file reproduces the same `_make_llm()` + `_make_state()`
helpers from scratch. It should be a canonical pattern so new test files don't
invent variations.

**Action:** Create `.claude/skills/langgraph-testing/SKILL.md` with the 3 helper
patterns + autouse fixture templates.

---

### 1.4 `config-from-yaml-with-types` update (extend existing skill)

**What:** The `CategoryEntry` pattern: Pydantic sub-model used as a typed list inside
`Settings`, populated from a YAML `list of dicts`. This is the "config as typed data"
pattern — config drives runtime behavior (number menus, Qdrant filters), not just
string constants.

**Where today:**
- `api/src/habitantes/config.py` → `CategoryEntry`, `categories: list[CategoryEntry]`
- `config/base.yaml` → `categories:` list block

**Why update:** The existing `config-driven-settings` skill covers scalars and env vars
but has no example of a typed sub-list. This is a frequent need for any system with
menu-driven UX or multi-tenant filtering.

**Action:** Add a `CategoryEntry`-style section to
`.claude/skills/config-driven-settings/SKILL.md` under "Typed sub-model lists".

---

### 1.5 `smoke-test` skill

**What:** The pattern for manual end-to-end scenario scripts: isolated `chat_id` per
scenario, labeled turns, structured console output (intent / category / confidence /
sources), optional CLI filter. Mirrors integration tests so the same paths are
covered by both.

**Where today:** `smoke_test.py` (root)

**Why a skill:** Every agent project needs a smoke test. The pattern (scenarios list,
`_turn()` helper, runner loop, CLI filter) is reusable but currently undocumented.

**Action:** Create `.claude/skills/smoke-test/SKILL.md` + `templates/smoke_test.py`

---

## 2. Gaps in Existing Rules (CLAUDE.md)

Rules that should be added to CLAUDE.md or the relevant skill because they were
learned the hard way during T1–T2 and are not written down anywhere.

---

### 2.1 Pre-commit hook auto-formats files

**Lesson:** `ruff-format` runs on `git commit` and reformats staged files. If you
commit immediately after, the hook runs again on already-reformatted files (two-pass
loop). The fix is to always `git add <files>` a second time after the first failed
commit attempt. Claude currently re-stages manually, but this is not in any rule.

**Where to add:** `CLAUDE.md` → "Copilot mistakes" section or as a note in
`github-commit-assistant/SKILL.md`.

**Rule to add:**
> After a failed `git commit` due to `ruff-format`, re-stage the same files and
> commit again. The hook formats in-place; the second commit will pass.

---

### 2.2 `_llm = None` must be reset alongside `_get_llm`

**Lesson:** When monkeypatching `_get_llm` in tests, the already-cached `_llm`
module-level singleton is NOT reset. Tests must patch both:
```python
monkeypatch.setattr(nodes_module, "_get_llm", lambda: mock)
monkeypatch.setattr(nodes_module, "_llm", None)
```
If only `_get_llm` is patched, the cached real LLM instance is used on the first
call.

**Where to add:** `CLAUDE.md` → "Copilot mistakes" section.

**Rule to add:**
> When patching a lazy factory (`_get_llm`, `_get_qdrant_client`, etc.) in tests,
> always also reset the cached singleton to `None` on the module:
> `monkeypatch.setattr(module, "_llm", None)`

---

### 2.3 `_categories_cache` must be reset in tests that use `monkeypatch`

**Lesson:** `categories_module._categories_cache` is a module-level singleton.
Tests that patch `_get_categories` must also reset the cache or the patched function
is never called (cache hit on the real data).

**Where to add:** `CLAUDE.md` → "Copilot mistakes" or `langgraph-testing` skill.

**Rule to add:**
> When patching `_get_categories`, also reset the cache:
> `monkeypatch.setattr(categories_module, "_categories_cache", None)`

---

### 2.4 Embedding dimensions must match ingestion pipeline exactly

**Lesson:** `config/base.yaml` had `e5-small` (384d) but the ingestion scripts use
`e5-large` (1024d). The mismatch only surfaces at query time (Qdrant rejects vectors
with wrong dimension). There is no compile-time check.

**Where to add:** `CLAUDE.md` → "What we learned" or ingestion-specific rule.

**Rule to add:**
> The embedding model in `config/base.yaml` (`llm.embedding_model_name`) must match
> the model used in the ingestion pipeline scripts. Dimension mismatch is silent until
> Qdrant raises a vector size error at query time. Current model: `e5-large` → 1024d.

---

### 2.5 `load_dotenv()` must be called before `Settings` is instantiated

**Lesson:** `pydantic-settings` `BaseSettings` reads `os.environ` at instantiation.
If `.env` is never loaded, secrets like `OPENAI_API_KEY` are missing even if the file
exists. `Settings(env_file=...)` only works when `BaseSettings` instantiates normally,
not when the settings dict is built manually from YAML first (our pattern).

**Where to add:** `config-driven-settings/SKILL.md` and `CLAUDE.md`.

**Rule to add:**
> Call `load_dotenv(root_dir / ".env", override=False)` at the top of `load_settings()`
> before constructing `Settings(**config_data)`. Otherwise secrets from `.env` are
> silently missing when the YAML-first loading pattern is used.

---

### 2.6 Optional fields for service tokens not required by domain layer

**Lesson:** `TelegramConfig.bot_token` was a required field, blocking all tests and
the domain layer from running without Telegram credentials.

**Where to add:** `CLAUDE.md` → "Core Rules" or "Copilot mistakes".

**Rule to add:**
> Infrastructure-specific tokens (Telegram, Slack, etc.) should be optional
> (`Field(default="")`) in config. The domain layer must be runnable without them.
> Required credentials: only what the inference path actually calls (e.g. `OPENAI_API_KEY`).

---

## 3. Missing Conventions (not in any file)

Patterns that are consistently applied in the code but never documented.

---

### 3.1 Section header comments (`# ── Name ───...`)

All files use the `# ── Section ────` banner style for visual sectioning.
This is not in any coding guideline. Should be added to `python-dev/SKILL.md`
or `python-patterns/SKILL.md` as the standard comment style for module-level sections.

---

### 3.2 `_make_state(**overrides)` pattern in unit tests

Every test file that tests nodes creates a `_make_state()` helper that builds a
minimal valid `AgentState` dict with sensible defaults, then applies `**overrides`.
This prevents brittle tests when new state fields are added (only the helper needs
updating). Should be in `langgraph-testing` skill.

---

### 3.3 Docstring convention for tools

Tools use a structured docstring block:
```
Contract:
  function_name(args) -> {"key": [...]} on success
                      -> {"error": {...}} on failure

Strategy: <brief description>
```
This is not documented anywhere. Should be in `python-dev/SKILL.md`.

---

### 3.4 `# ── Static responses ───` block in nodes

Static string responses (decline, clarification, fallback) live in a clearly
labeled block at the top of `nodes.py`, not scattered throughout the file or
inside functions. This makes them easy to find and translate. Not documented.

---

### 3.5 Checkpoint convention

Sessions that complete a task milestone should produce a
`.claude/checkpoints/<TASK_ID>-CHECKPOINT.md` with: what was done, key files,
test count, architecture snapshot, and resume instructions. This convention was
invented ad-hoc in T2. Should be formalized as a post-task habit in `CLAUDE.md`.

**Rule to add to CLAUDE.md:**
> After completing a task milestone (T2.*, T3.*, etc.), write a checkpoint:
> `.claude/checkpoints/<ID>-CHECKPOINT.md` with architecture snapshot, key files,
> test count, and next steps. This is the resume artifact for the next session.

---

## 4. Agent/Skill Overlaps to Resolve

Things that are duplicated or unclear about when to use what.

---

### 4.1 `coding-guidelines` vs `python-dev` overlap

Both skills cover code quality. `coding-guidelines` is project-specific (eval gate,
agent constraints). `python-dev` is general Python style. The SKILL.md index table
lists both for "review code quality" which is ambiguous.

**Action:** Clarify in `SKILL.md` index:
- `coding-guidelines` → use when reviewing agent system code (nodes, tools, graph)
- `python-dev` → use when reviewing general Python (config, utils, schemas, tests)

---

### 4.2 `Tech Architect` agent is unused after T2 graph stabilized

The `tech-architect.agent.md` was invoked for T2 design review. Once the graph
topology is stable, it's unlikely to be needed again until T3 (FastAPI layer) or
significant state changes. The agent is listed in the context menu and burns tokens
on every session.

**Action:** Either remove it from the agents folder and invoke only when needed,
or add a `trigger:` note in the agent header: "Use only when design.md, state.py,
or contracts change."

---

### 4.3 `github-commit-assistant` vs commit pattern in CLAUDE.md

CLAUDE.md has no commit convention. `github-commit-assistant` has the convention.
But the skill name (`github-commit-assistant`) doesn't appear in the SKILL.md "when
to use" table under a natural trigger. The rename to `github-commit-guidelines`
(visible in `/context`) exists but is inconsistent.

**Action:** Reconcile the skill name and add "commit messages, organize commits" row
to SKILL.md index pointing to the correct skill name.

---

## 5. settings.local.json — Permissions to Review

Current state after T2:
```json
"allow": [
  "Bash(python:*)", "Bash(source:*)", "Bash(.venv/bin/python:*)",
  "Bash(pytest:*)", "Bash(docker ps:*)",
  "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)",
  "Bash(git add:*)", "Bash(git commit:*)", "Bash(git push origin dev:*)"
]
```

**Missing for T3 (FastAPI + Docker work):**
- `Bash(docker compose:*)` — starting/stopping local stack for integration testing
- `Bash(curl:*)` — testing API endpoints manually
- `Bash(uvicorn:*)` — running the API locally without Docker
- `Bash(pip install:*)` or `Bash(uv pip install:*)` — adding dependencies

**Intentionally keep requiring approval:**
- `git push origin main` — never auto-allow
- `docker compose down -v` — destroys volumes
- `rm -rf:*` — destructive filesystem

**Action:** Add T3 permissions when starting the infrastructure layer to avoid
constant interruptions during API/Docker development.

---

## 6. CLAUDE.md Structural Issues

### 6.1 `tasks.md` is out of sync

The `tasks.md` still lists T1.2 as unchecked, but config was implemented
(it's tested with 4 passing unit tests). Also T2.2 references `category.py` which
was deleted.

**Action:** Audit and update `tasks.md` so it reflects actual done/not-done state.

### 6.2 "What we learned" section is thin

CLAUDE.md's "Copilot mistakes" section has 6 bullets from project inception.
T2 generated at least 6 more learnable rules (see Section 2 above). The section
should be updated after every task milestone.

### 6.3 `docs/standard/agent-systems-standard.md` is referenced but may not exist

`tech-lead.agent.md`, `tech-architect.agent.md`, and `coding-guidelines/SKILL.md`
all reference `docs/standard/agent-systems-standard.md`. Verify this file exists;
if not, either create it (extract rules from CLAUDE.md) or update the references.

**Action:** `ls docs/standard/` and fix or create the referenced file.

---

## 7. Lessons from Task 3 (Evaluation Pipeline)

These are patterns and insights gained while implementing and running the RAG evaluation suite.

### 7.1 Hit Rate vs. Recall for RAG "Sufficiency"

**Insight:** Recall measures completeness (finding *all* relevant documents). For RAG, this is often too strict because the LLM only needs *one* good document to answer (sufficiency). In our tests, Recall was ~51% while Hit Rate was ~89%.
**Suggestion:** Always include `Hit Rate@k` alongside `Recall@k`. If Hit Rate is high but Recall is low, focus on deduplicating the Knowledge Base or tuning the RAG prompt rather than the search engine.

### 7.2 Explicit ID-based Evaluation

**Insight:** Originally, evaluation relied on parsing the "source" string (e.g. "Opening a Bank Account"). This is brittle and ambiguous if multiple documents have the same source.
**Suggestion:** Modify search tools to return an explicit, immutable `thread_id` or `uuid` in the metadata. Use these IDs for all retrieval metrics (`Recall`, `Precision`, `MRR`) to ensure 100% accuracy in the evaluation math.

### 7.3 The "Faithfulness" vs. "Precision" Gap

**Insight:** Our bot achieved **1.0 Faithfulness** but only **0.42 Context Precision**. This means the search results contain a lot of "noise" (irrelevant chunks), but the LLM is excellent at ignoring that noise and focusing only on the relevant part.
**Suggestion:** To improve the system without risking the stable LLM prompts, focus on **Reranking**. Adding a cheap Cross-Encoder (e.g. `BGE-Reranker`) before passing chunks to the LLM can drastically improve Context Precision and lower token costs/latency.

### 7.4 Evaluation Parallelization

**Insight:** Running E2E evaluation for 38 cases takes several minutes because it runs sequentially (LLM calls are slow).
**Suggestion:** Update `run_eval.py` to use `asyncio.gather` or a `ThreadPoolExecutor` for the `run_generation_eval` portion. This is safe because evaluation is a stateless batch process.

### 7.5 Golden Dataset as "Living Documentation"

**Insight:** The 38 questions in `golden_dataset.json` are the best documentation of what the bot is *actually* expected to know.
**Suggestion:** Encourage the user to add "tricky" real-world questions encountered in manual smoke tests directly to the golden set. This transforms the evaluation from a one-off task into a continuous regression suite.

---

## 8. Lessons from Task 3.5 (Hybrid Search Refinement)

These are lessons from the synchronization of the ingestion and retrieval pipelines.

### 8.1 Synchronization of Normalization

**Lesson:** If the ingestion pipeline produces BM25 vectors from raw text but the retrieval pipeline uses normalized text (accent-insensitive), the lexical match will fail for common Portuguese words like "SÉCURITÉ" vs "securite".
**Rule:** Every text transformation (stripping accents, lowercase, glossary expansion) MUST be identical in both `3-build_qdrant_collection.py` and `habitantes.domain.tools.py`.

### 8.2 Glossary Enrichment in Retrieval

**Lesson:** Expanding synonyms only during ingestion is not enough if the user uses a synonym that doesn't appear in the original text.
**Suggestion:** Apply the same `enrich_bm25_input` function in the retrieval logic. If a user asks about "visto", the engine should also search for "visa" and "titre de sejour" to find relevant chunks that might use those technical terms.

### 8.3 FastEmbed BM25 Stability

**Lesson:** `fastembed`'s BM25 implementation provides better stability and performance for Portuguese than basic hashing approaches.
**Action:** Ensure the `sparse_model` names and parameters match between the script and the tool.

---

## 9. Lessons from Task 3.6 (Tools Refactoring)

### 9.1 Package Extraction

**Insight:** Large modules like `tools.py` that handle embeddings, ranking, and search logic become hard to maintain and navigate.
**Suggestion:** Extract related functionality into a dedicated package (e.g. `domain/tools/` with `_embedding.py`, `_ranking.py`, `search.py`). Use `__init__.py` to export the public API so the rest of the application imports from the package normally.

### 9.2 Test Suite Mocking Robustness

**Insight:** When refactoring a module into a package, `monkeypatch` calls in the test suite that depend on specific internal paths (like `_get_dense_model`) will break.
**Suggestion:** Expose the internal globals and functions via the package's `__init__.py` to maintain backward compatibility for test patching, or explicitly update all test files to patch the new submodules.

### 9.3 Import Resolution during Refactoring

**Insight:** When moving modules, standard IDE refactoring tools might not catch dynamic imports or fixtures in tests.
**Suggestion:** After extracting a package, always run `grep` across the codebase to find all import references to the old module path and update them systematically using `sed` or IDE tools before running tests.

---

## 10. Lessons from Task 4 (FastAPI + Telegram Bot)

These are lessons from the infrastructure layer (FastAPI service and Telegram bot integration).

### 10.1 Trace ID Middleware Persistence

**Lesson:** When implementing trace ID middleware, the ID must be explicitly retrieved from `request.state` in the endpoint. If the endpoint generates its own ID, the logs and the response will be out of sync, breaking auditability.
**Action:** Always use `X-Trace-Id` headers and `request.state.trace_id` as the single source of truth for a request's lifecycle.

### 10.2 Telegram Formatting Robustness

**Lesson:** Telegram's `MarkdownV2` is extremely sensitive to special characters (like `.`, `-`, `!`) which are common in RAG responses.
**Action:** Use `ParseMode.MARKDOWN` (v1) or `HTML` for RAG responses to avoid frequent "Entity_parse_failed" errors, or implement a strict character escaper.

### 10.3 Per-Chat Locks and Deduplication

**Lesson:** Users often double-tap buttons or send multiple messages while waiting for an LLM response.
**Action:** Implement `asyncio.Lock` per `chat_id` and a simple message ID deduplication set to prevent the bot from processing the same intent multiple times in parallel.

### 10.4 Typing Indicators for Perceived Performance

**Lesson:** A 5-10 second RAG delay feels like a bug to users if the bot is silent.
**Action:** Send `ChatAction.TYPING` immediately after receiving the message, before starting the long-running HTTP call to the agent.

### 10.5 Dependency Alignment (Bot vs API)

**Lesson:** The bot and API often run in different containers but share the same domain logic/config.
**Action:** Keep `app/requirements.txt` in sync with the root `pyproject.toml` or use a shared base image to avoid version mismatches during deployment.

---

## 11. Lessons from Task 5 (Docker & Deployment)

These are lessons from the containerization and final verification phase.

### 11.1 Standardized Docker Orchestration

**Lesson:** Maintaining separate Dockerfiles for API and Bot but sharing the same domain logic works best when using a unified `docker-compose.yml`.
**Action:** Always use the `api/src` folder as part of the build context for both services if they share domain logic.

### 11.2 Eval Gate as Deployment Quality Control

**Lesson:** The `run_eval.py` script serves as a critical gate. If it fails, the production environment might be serving hallucinations or using incorrect retrieval parameters.
**Action:** Integrate `make test` and `make eval` into the CI pipeline (or manual check before `docker compose up --build`).

---

## 12. Lessons from Task 6 (MVP Hardening)

### 12.1 Configuration Centralization (YAML vs Env)

**Lesson:** Tuning constants (k-values, weights, lambdas) are hard to manage via environment variables.
**Action:** Use a `base.yaml` for all tuning defaults and only use `.env` for secrets (API keys) and environment overrides (URLs). This makes the configuration significantly more readable and easier to version control.

### 12.2 Anti-Spam and Cost Protection

**Lesson:** Without `max_tokens` and rate limiting, a single user or a bug can quickly drain the OpenAI quota.
**Action:** Implement `max_tokens` at the LLM levels and per-user message rate limits (messages per minute/hour) at the entry points (FastAPI middleware and Telegram bot).

### 12.3 Clean Package Exports

**Lesson:** Deep import paths (e.g., `from habitantes.domain.tools.search import run`) leak internal structure.
**Action:** Use `domain/__init__.py` to expose a stable public API. This decouples the infrastructure layer from internal domain refactorings.

### 12.4 Background Task Cleanup

**Lesson:** In-memory tracking (for deduplication or rate limiting) grows indefinitely.
**Action:** Always implement a background cleanup task (e.g., `asyncio.create_task`) when using in-memory caches or sets in long-running processes like a Telegram bot.

---

---

## 13. Lessons from Task 6.5 (Ingestion Standardization)

### 13.1 Standardized Artifact Naming

**Lesson:** Using dynamic filenames based on input timestamps (e.g., `chat-xxxx-classified.csv`) makes it difficult to wire subsequent pipeline stages via configuration.
**Action:** Enforce fixed filenames (`classified.csv`, `qa_pairs.json`, `synthesis_results.jsonl`) within a directory named after the source file's stem. This creates a predictable structure for all stages.

### 13.2 Per-Chat Isolation

**Lesson:** Mixing artifacts from different raw sources in a single `artifacts/` folder leads to confusion and accidental overwrites.
**Action:** Always create a parent directory under `artifacts/` named after the input file. This ensures each raw export has its own complete set of processed files, acting as a "parent to processed" standard.

### 13.3 Unified Pipeline Entrypoint

**Lesson:** Running multiple numbered scripts manually is error-prone and hard to document.
**Action:** Consolidate all ingestion stages into a single `pipeline.py` orchestrator. This ensures that configuration is loaded once and all stages share the same working context and output paths.

### 13.4 Automatic Directory Management

**Lesson:** Pipeline stages often fail if the output directory doesn't exist.
**Action:** Each module/stage should proactively call `mkdir(parents=True, exist_ok=True)` on its target path.

---

## 14. Lessons from Task 6.1 (Refactoring & Stale Tests)

### 14.1 Brittle Mocking in Integration Tests

**Lesson:** When refactoring public-facing domain functions (e.g., `run` -> `run_agent`), ensure that all integration test patches are updated accordingly. Mocking strings like `patch("habitantes.infrastructure.api.routers.chat.run")` are brittle as they are not caught by type checkers or IDE rename tools if they are plain strings.
**Action:** After any significant domain API change, run the full test suite (`pytest tests/ -v`) to catch `AttributeError` in mocks. Consider using autospec or object-based patching where possible, though string-based patching is often necessary for FastAPI routers.

---

## 15. Lessons from Docker Debugging Session

### 15.1 Qdrant image has no curl or wget

**Lesson:** `qdrant/qdrant` is a minimal image with no standard HTTP tools. A health check using `CMD curl -f http://localhost:6333/healthz` always exits with "executable not found", permanently marking the container unhealthy even though Qdrant is running fine.
**Action:** Use a bash TCP health check instead:
```yaml
healthcheck:
  test: ["CMD", "bash", "-c", "exec 3<>/dev/tcp/localhost/6333 && echo -e 'GET / HTTP/1.0\r\n\r\n' >&3 && cat <&3 | grep -q qdrant"]
```
Before writing a health check for any third-party image, verify which tools are available inside it.

---

### 15.2 `docker compose restart` does not reload env_file

**Lesson:** `docker compose restart <service>` restarts the existing container process but does NOT recreate the container. Environment variables from `env_file` are baked in at container creation time. Changes to `.env` are invisible after a plain restart.
**Action:** Always use `docker compose up -d --force-recreate <service>` after changing `.env` values to pick up the new environment.

---

### 15.3 Inter-container URLs must use Docker service names

**Lesson:** Inside a Docker container, `localhost` resolves to the container itself, not to other services in the compose network. Setting `API_URL=http://localhost:8000` in `.env` means the Telegram bot tries to call itself instead of the `api` container.
**Action:** Use the compose service name as the hostname for inter-service calls: `API_URL=http://api:8000`. Reserve `localhost` URLs only for host-machine access (e.g., during local dev outside Docker).

---

### 15.4 `Path(__file__).parents[N]` breaks with bind-mounts

**Lesson:** The config loader used `Path(__file__).parents[3]` to find `config/base.yaml` relative to the source file. Locally the path is `repo/api/src/habitantes/config.py` (needs 3 parents to reach repo root). Inside Docker the source is mounted at `/app/src/habitantes/config.py` (only 2 parents to reach `/app`). The path calculation breaks silently with a `FileNotFoundError`.
**Action:** Add a `CONFIG_DIR` env var to make the path explicit and environment-independent:
```python
config_dir = Path(os.environ.get("CONFIG_DIR", str(root_dir / "config")))
config_path = config_dir / "base.yaml"
```
Set `CONFIG_DIR=/app/config` in docker-compose for each service that loads settings. Locally no override is needed since the default resolves correctly.

---
