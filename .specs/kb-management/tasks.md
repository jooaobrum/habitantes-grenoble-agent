# KB Management — Tasks

Atomic tasks. Implement one at a time; `pytest tests/ -v` stays green after each. See
[spec.md](spec.md) / [design.md](design.md).

## Phase 1 — Queue foundation (offline, no browser)

- **T1 · Review store** — `tools/review/store.py`: SQLite schema + `init_db`, `upsert_pending`,
  `list_items(status/reason/category/text)`, `get`, `set_status`, `save_edits`.
  *Done when:* unit test creates a db, inserts, filters, transitions status, persists edits.

- **T2 · Queue builder** — `tools/review/build_queue.py` (CLI): read `synthesis_results.jsonl`, run
  `should_drop`, `INSERT OR IGNORE` dropped records as `pending` with reasons; print status counts.
  *Done when:* first run populates pending; a second run leaves decided rows untouched (idempotency test).

- **T3 · KB writer** — `tools/review/kb_writer.py`: whitelist `build_payload` (no PII, synthesized answer),
  cached embedder, `_assert_dim_matches`, `upsert_item`, `delete_item`; collection/url/model from `settings`.
  *Done when:* test asserts payload has none of `question_user`/`answer_users`/`context` and uses the
  synthesized answer; upsert/delete call the (mocked) Qdrant client with the stable `point_id`.

## Phase 2 — Streamlit console

- **T4 · App** — `tools/review/app.py`: filters, paginated list, inline edit, Validate/Archive/Delete/Save
  buttons, `@st.cache_resource` embedder + client.
  *Done when:* `make review` launches; validating an item upserts to Qdrant and flips status to `validated`.

- **T5 · Wiring** — `make review` target; `streamlit` in a `tools` dependency group in `pyproject.toml`;
  `review:` block in `config/base.yaml`.
  *Done when:* `uv sync --group tools && make review` works from a clean env.

## Phase 3 — Hardening, verify, docs

- **T6 · Dim guard + audit trail** — enforce `_assert_dim_matches` on startup; append every decision to
  `artifacts/review/decisions.jsonl`.
  *Done when:* wrong-model config refuses to write; each action appends one audit line.

- **T7 · Docs** — `tools/review/README.md` (build → review → act) + one line in the main README.
  *Done when:* a new engineer can run the full loop from the README alone.

## Verification (end-to-end)

1. `python -m tools.review.build_queue` → prints pending count.
2. `pytest tests/review/ -v` green.
3. `docker compose up qdrant`, `make review`, edit + **Validate** one item.
4. Scroll Qdrant by that `point_id` → payload present, PII-free, `answer` = synthesized text. **Delete** → gone.
5. Re-run `build_queue` → decided items stay decided.
6. `pytest tests/ -v` green (no regression).
