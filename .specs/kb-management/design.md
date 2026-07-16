# KB Management — Design

See [spec.md](spec.md) for intent and decisions.

## Boundary

Ingestion-side tool under `tools/review/`. It imports **ingestion** helpers and **config** settings only —
never `habitantes.domain.agent` / nodes / prompts. The agent/query path is untouched. Runs offline.

## Components

```
tools/review/
  store.py          SQLite review store (status + edits)          ← state
  build_queue.py    synthesis_results.jsonl → pending items       ← offline CLI
  kb_writer.py      whitelist payload + embed + upsert/delete      ← Qdrant I/O (thin)
  app.py            Streamlit console (list/filter/edit/act)       ← UI
  config.py|README  paths + how-to
tests/review/       store, build_queue idempotency, PII-free payload
```

Data flow: `synthesis_results.jsonl → build_queue → review.db → app.py → kb_writer → Qdrant`.

## Review store (SQLite — stdlib `sqlite3`, no new dep)

`artifacts/review/review.db`, table `review_items`:

| column | notes |
|---|---|
| `point_id` TEXT PK | `stable_point_id(rec)` — same ID the loader would use → idempotent |
| `status` TEXT | `pending` \| `validated` \| `archived` \| `deleted` |
| `reasons` TEXT (JSON) | drop reasons from `should_drop` |
| `source_path` TEXT | provenance |
| `question,answer,category,subcategory,tags,key_terms,confidence,thread_id,thread_start,question_time` | whitelisted original fields (tags/key_terms JSON) |
| `edited` TEXT (JSON, nullable) | human field overrides; effective value = edited ?? original |
| `note` TEXT | reviewer note |
| `in_qdrant` INTEGER | 1 after a successful validate upsert |
| `updated_at` TEXT | ISO timestamp |

SQLite (not JSONL) because status/edits mutate per click; rewriting a 5k-line JSONL each action is wasteful.

**Idempotency:** `build_queue` does `INSERT OR IGNORE` on `point_id` — new drops appear as `pending`,
already-decided rows are never reset.

## kb_writer (thin Qdrant wrapper)

- `_embedder()` — `@lru_cache`d `SentenceTransformer(settings.llm.embedding_model_name)`.
- `_assert_dim_matches(collection)` — refuse to write if embedder dim ≠ live collection's dense dim
  (guards the e5-small/large corruption in audit P0-5).
- `build_payload(item)` — explicit **whitelist** (spec). Picks `synthetic_answer` else `answer`. No PII keys.
- `upsert_item(item)` — reuse `build_sparse_text`, `stable_point_id`, `ensure_collection`, `upsert_points`.
- `delete_item(point_id)` — `qclient.delete(...)` by ID.
- Collection / URL / model all from `settings` so the console always targets what the live API targets.

## app.py (Streamlit)

- `@st.cache_resource` embedder + Qdrant client (load the 2.2 GB model once).
- Sidebar: status (default `pending`), reason, category, text search.
- Paginated list; each item: editable `question`/`answer`/`category`/`subcategory`/`tags`/`key_terms`,
  reason chips, confidence; buttons **Validate** / **Archive** / **Delete** / **Save edits**.
- Optional: checkbox + "Validate selected" bulk action.

## Config

Add a `review:` block to `config/base.yaml` (`db_path`, `source_glob`), read via ingestion settings — no
hardcoded paths (config-driven-settings rule). Qdrant collection/url/model come from the API `settings`.

## Reuse (no change to existing files)

`ingestion/load/qdrant.py`: `should_drop`, `build_sparse_text`, `dense_embed_questions`, `stable_point_id`,
`ensure_collection`, `upsert_points`. **Not** `make_payload` (PII/diverged). Settings from
`api/src/habitantes/config.py`.
