# P0-04 · Fix ingestion answer contract + PII whitelist + one embedding model

**Phase:** 0 — Stabilize · **Priority:** P0 (do before any re-ingest) · **Audit:** P0-3, P0-5

## Problem
The deployed KB came from an older pipeline (clean synthesized `answer`, no names). Current code diverged:
- [synthesis.py:95-114](../../../ingestion/preprocess/synthesis.py) keeps the raw multi-user WhatsApp concat in `answer` and writes the clean text to an unused `synthetic_answer`.
- [qdrant.py:163-171](../../../ingestion/load/qdrant.py) `make_payload` does `dict(rec)` — copying `question_user`, `answer_users`, and `context` (real names, confirmed in `qa_pairs-high.json`) into Qdrant, breaking the spec's anonymization guarantee.
- The API serves `payload["answer"]` ([search.py:179-193](../../../api/src/habitantes/domain/tools/search.py)).
- Embedding model is inconsistent: [config.py:20](../../../api/src/habitantes/config.py) default `e5-small` vs [base.yaml:4](../../../config/base.yaml) `e5-large` vs hardcoded `e5-large` in [qdrant.py:202](../../../ingestion/load/qdrant.py). Mismatch → dimension error on every search.

## Change
- `synthesis.py`: write the synthesized text to `answer` (keep raw as `raw_answer` if lineage is wanted).
- `make_payload`: replace `dict(rec)` with an explicit **whitelist**: `question, answer, category, subcategory, tags, key_terms, thread_id, thread_start, question_time, tier, confidence`.
- Verify [should_drop](../../../ingestion/load/qdrant.py) reads fields that actually exist post-change (tier/confidence/answer).
- Make the loader read `settings.llm.embedding_model_name` instead of hardcoding; confirm base.yaml and config default agree on one model. If VPS RAM < 8 GB, set `e5-small` everywhere and plan a `make load-only` re-embed.

## Done when
- [ ] `make ingest` on a copy → Qdrant payloads contain **no** `question_user` / `answer_users` / `context`.
- [ ] Payload `answer` is the synthesized text, not raw chat.
- [ ] Dense query dim == index dim (search returns chunks, no dimension error).
- [ ] One embedding model name referenced across config, API, and loader.
