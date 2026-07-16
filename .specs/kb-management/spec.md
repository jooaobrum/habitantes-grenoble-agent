# KB Management — Human Validation Console

**Status:** Draft · **Owner:** 1 engineer · **Type:** ingestion-side curation tool (offline, never at query time)

## Context — why this exists

The ingestion pipeline produces `artifacts/<chat>/synthesis_results.jsonl` (~2.8k LLM-synthesized Q&A
records). At load time, [`should_drop`](../../ingestion/load/qdrant.py) silently discards every record
flagged for *any* reason — `needs_human_review`, `confidence < 0.65`, `info_might_be_outdated`,
`tier == "low"`, `category == "General"`, COVID tags, time-relative wording. **That knowledge is lost with
no human in the loop.** There is no way today to look at a flagged pair, fix it, and keep it.

This feature adds a **small curation console** to work through that drop pile: for each pair — **validate**
(optionally edit first) → embed + upsert into the live Qdrant collection; **archive** (keep out of the KB,
stop resurfacing); or **delete**. Few clicks, easy, offline.

It is an **ingestion-side tool**. It never imports agent logic and never runs at query time — it satisfies
the constitution's "ingestion is separate from inference" and "UI never imports agent logic" rules
(the agent path is untouched).

## Decisions

- **Interface:** Streamlit app (`tools/review/app.py`). Sanctioned by CLAUDE.md ("Streamlit/Gradio script is fine").
- **Queue scope:** *all* records `should_drop` rejects, each tagged with its drop reason(s).
- **Qdrant target:** validate writes **directly into the live collection** (`habitantes_chat_kb_hybrid`,
  `intfloat/multilingual-e5-large`, dense dim 1024) with stable, idempotent point IDs.

## What the system does

1. **Build the queue** (offline CLI): read `synthesis_results.jsonl`, run `should_drop`, insert each dropped
   record as a `pending` review item with its reasons. Idempotent — re-running never resets a decided item.
2. **Review** (Streamlit): filter by status / reason / category / text; per item, edit the fields, then act.
3. **Act** — one click each:
   - **Validate** → embed (e5-large) + upsert to the live collection; status `validated`, `in_qdrant=1`.
   - **Archive** → status `archived`; not written to Qdrant; hidden from the default queue.
   - **Delete** → delete the point from Qdrant if present; status `deleted`; hidden.
   - **Save edits** → persist field edits without changing status.

## Status lifecycle

`pending` → (Validate) → `validated` · (Archive) → `archived` · (Delete) → `deleted`.
Any state is re-actionable (re-validate re-upserts the same `point_id`; delete removes it). Transitions are
idempotent and append to a decisions audit log.

## Payload whitelist (the Qdrant contract — aligns with audit P0-04)

Written to Qdrant on validate:
`question, answer, category, subcategory, tags, key_terms, thread_id, thread_start, question_time,
confidence` + `_review = {validated_by_human: true, validated_at, note}`.

- `answer` = `synthetic_answer` if present, else `answer` (the synthesized text — never raw chat concat).
- **Never** written: `question_user`, `answer_users`, `context` (PII). Anonymization holds by construction.

## Out of scope

Cross-encoder reranker, LangGraph, Redis/Postgres, query-time admin dashboards, multi-user auth. This is a
single-engineer local curation tool.

## Done when

- [ ] `build_queue` populates the review store from `synthesis_results.jsonl` with correct drop reasons; a
      second run leaves already-decided items untouched.
- [ ] Streamlit console lists/filters items and exposes Validate / Archive / Delete / Save edits.
- [ ] Validate upserts to the **live** collection; the point's payload contains **no**
      `question_user`/`answer_users`/`context`, and `answer` is the synthesized text.
- [ ] Delete removes the point from Qdrant.
- [ ] Embedding model + collection are read from `settings` and match the live index (dim guard refuses on mismatch).
- [ ] `pytest tests/review/ -v` and the existing `pytest tests/ -v` both pass.

## Reference

- Design: [design.md](design.md) · Tasks: [tasks.md](tasks.md)
- Reused helpers: [ingestion/load/qdrant.py](../../ingestion/load/qdrant.py)
  (`should_drop`, `build_sparse_text`, `dense_embed_questions`, `stable_point_id`, `ensure_collection`,
  `upsert_points`) — but **not** `make_payload` (leaks PII / diverged contract).
- Settings: [api/src/habitantes/config.py](../../api/src/habitantes/config.py).
