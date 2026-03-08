# RAG Pipeline Improvements Report - Habitantes Grenoble

This report summarizes the evolution of the RAG (Retrieval-Augmented Generation) pipeline performance, detailing the architectural and prompt-level optimizations implemented to reach the current performance state.

## 🚀 Optimization Journey

### 1. Hybrid Search Refinement (Weighted RRF)
Originally, retrieval used a simple semantic search. We transitioned to a **Weighted Hybrid Search** strategy:
- **Weights**: 0.7 Dense (Semantic understanding via E5 Large) / 0.3 Sparse (Keyword matching via BM25).
- **Manual RRF implementation**: Since the Qdrant client's `FusionQuery` does not support custom weights, we implemented a custom ranking logic that combines results from separate dense and sparse prefetch calls.
- **Benefit**: Significantly improved retrieval of niche/specific terms (e.g., "requeijão", "massa de pastel") that semantic-only search often missed.

### 2. Ingestion & Pre-processing Standardization
Standardized the normalization and enrichment pipeline to ensure parity between how data is stored and how queries are processed:
- **Normalization**: Lowercase converting and stripping accents.
- **Glossary Enrichment**: Queries are now enriched with local domain terms (e.g., specific French bureaucracy acronyms) before sparse embedding.
- **Categorization**: Implemented a two-pass classification to filter noise and improve precision.

### 3. Synthesis Prompt Optimization
The synthesis engine was initially too conservative, frequently falling back to "Information not found" or adding redundant warnings about dated information.
- **Relaxed Guardrails**: Instructed the LLM to infer useful answers from available fragments while maintaining a professional tone.
- **Removed Meta-Commentary**: Eliminated mandatory warnings regarding outdated data, allowing for more direct and relevant responses.
- **Answer Relevance Impact**: This was the primary driver for the jump from ~0.52 to ~0.75 in Answer Relevance.

### 4. Continuous Date Decay
Implemented an exponential decay factor in the retrieval ranking to prioritize newer information:
- **Formula**: `Score = Base_Score * exp(-days_old * 0.0005)`.
- **Logic**: Information from 1 year ago maintains ~83% relevance, while 5-year-old threads decay to ~36%.
- **Benefit**: Ensures the bot favors recent community advice without losing historical knowledge that may still be valid.

### 5. Key-Term Inference from Query (`infer_key_terms_from_query`)
Added a new function `infer_key_terms_from_query()` in `tools/_ranking.py` that goes beyond glossary-only matching to infer meaningful search terms from any free-form query:
- **Free-token extraction**: Strips stopwords (PT + FR), extracts content words of 4+ chars — including proper nouns like "Oriade" or "Transmontano" that aren't in the domain glossary.
- **Portuguese stem variants**: Generates base forms for common plural/suffix patterns (`exames → exame`, `clínicas → clinica`, `ões → ão`, etc.) using a suffix-rules table, so both forms are included in BM25 enrichment.
- **Glossary-first, free-tokens-second**: Domain glossary matches (e.g. `titre de sejour`, `CAF`) are always placed first; greedy covering prevents double-counting overlapping tokens.
- **`enrich_bm25_input` upgraded**: Now delegates to `infer_key_terms_from_query` instead of the glossary-only `extract_key_terms`, enriching both ingestion and retrieval BM25 inputs consistently.

### 6. Payload Normalization at Ingestion (`key_terms` + `tags`)
Prior to this change, `key_terms` and `tags` in the Qdrant payload were stored as raw strings with original casing and accents (e.g. `"Oriade"`, `"clínica Belledonne"`), making them unmatchable against normalized query terms.
- **`_normalize_str_list()`** added to `3-build_qdrant_collection.py`: applies `strip_accents()` (lowercase + NFD → ASCII) to every item in `key_terms` and `tags` before upsert.
- **Deduplication preserved**: insertion-order-preserving set ensures no duplicate normalized terms.
- **Collection rebuilt** with `overwrite_collection=True` — 2853 points re-ingested with normalized payloads.

### 7. Anchor Reranking Extended to `key_terms` + `tags`
The `_rerank_with_anchors()` function in `tools/_ranking.py` previously matched query anchors only against `question`, `answer`, `category`, and `subcategory` payload fields.
- **Extended blob**: now also concatenates the (pre-normalized) `key_terms` and `tags` lists from the payload into the comparison string.
- **Effect**: proper nouns like `"oriade"` that appear in `key_terms` but not in the question or answer text now contribute to the anchor bonus score, pushing those chunks up in the reranked list.

### 8. Synthesis Prompt Rewrite — Mandatory Synthesis Rule
Diagnosed root cause of low `answer_relevance`: when context chunks existed but didn't perfectly match the question, the LLM defaulted to `"Não encontrei informações específicas..."` followed by generic advice — scored 0.4–0.7 by the LLM judge.

Key changes to `prompts/synthesis.py`:
- **Inverted fallback logic**: Changed from "use fallback only if irrelevant" (too permissive) to a hard rule: "If context is not empty, you MUST synthesize. NEVER open with 'Não encontrei' if chunks were provided."
- **Explicit partial-answer pattern**: Added a structural instruction with an example: answer the part the context covers, then signal the uncovered part at the end. Prevents the model from treating partial coverage as a failure.
- **Removed 19-category list**: The orchestrator handles routing before synthesis; the list (~120 tokens) was dead weight that provided no generation benefit.
- **Scope section removed**: Intent/scope classification happens upstream — the synthesis prompt only needs to focus on generation quality.

---

## 📊 Performance Benchmarks

The table below shows the progression of metrics compared to the initial Baseline.

| Metric | Baseline | Dedup + K | 50% Cat | D+C | key_terms + Prompt | Target | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Hit Rate@5** | 0.8947 | 0.9211 | 0.9474 | 0.9474 | **0.9737** | ≥ 0.80 | **PASS** |
| **Recall@5** | 0.4825 | 0.5088 | 0.5614 | 0.5614 | **0.6162** | ≥ 0.50 | **PASS** |
| **Context Precision** | 0.4211 | 0.4474 | 0.5132 | 0.5132 | **0.5425** | ≥ 0.50 | **PASS** |
| **Answer Relevance** | 0.5263 | 0.5526 | 0.6316 | 0.7526 | **0.9526** | ≥ 0.80 | **PASS** |
| **Faithfulness** | 0.8947 | 0.8947 | 0.9211 | 0.9412 | **0.9632** | ≥ 0.80 | **PASS** |
| **Semantic Similarity**| 0.8421 | 0.8684 | 0.8947 | 0.8947 | **0.9141** | ≥ 0.70 | **PASS** |

*Previous "Current (Final)" column (D+C) renamed to reflect that state; new column is the result after improvements 5–8.*

## 📈 Summary of Achievements
- **Hit Rate** improved by **~9%** from baseline, relevant document almost always in top 5.
- **Recall@5** improved by **~28%** from baseline, more relevant threads recovered per query.
- **Context Precision** improved by **~29%** from baseline, less noise in retrieved chunks.
- **Answer Relevance** improved by **~81%** from baseline — from frequent refusals (0.53) to substantive, grounded answers (0.95). The prompt rewrite (improvement 8) was the single biggest driver (+0.20 in the final step alone).
- **Faithfulness** remains high at **96%**, confirming the prompt change did not introduce hallucinations.
- **All 6 CI gate targets now pass.**

---
**Report updated on 2026-03-08**
