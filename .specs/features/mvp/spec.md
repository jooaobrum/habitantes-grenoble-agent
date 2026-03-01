# MVP — SPECIFY (WHAT)

## Problem statement

Brazilian expats in Grenoble repeatedly ask the same bureaucratic, housing, and daily-life questions in WhatsApp groups. Information is fragmented across 5 years of chat history (~10MB, ~3,964 Q&A pairs). A knowledge-based chatbot is needed to centralize and synthesize trusted answers in Portuguese, available 24/7 on Telegram.

## Scope

**In:**
- Single-turn Q&A via Telegram
- Portuguese language (native)
- 8 topic categories: visa, housing, healthcare, banking, transport, education, caf, general
- Hybrid search (dense + sparse) over curated knowledge base
- Source attribution in answers
- Basic feedback collection (thumbs up/down)
- Intent classification (greeting, qa, feedback, out-of-scope)
- Graceful handling of all failure modes

**Out:**
- Multi-turn memory persistence across sessions
- WhatsApp interface
- User personalization / profiles
- Real-time knowledge updates
- Admin dashboard
- Multi-language support
- Voice messages / image understanding

## Users & workflow (golden path)

**User**: Brazilian expat in Grenoble asks a question on Telegram in Portuguese.

**System**:
1. Receives message via Telegram bot
2. Classifies intent (greeting / qa / feedback / out-of-scope)
3. If QA → classifies category (visa, housing, etc.)
4. Routes: direct answer, RAG search, or clarification request
5. If RAG → hybrid search in Qdrant (dense + sparse, RRF fusion, top-5)
6. Synthesizes answer with gpt-4o-mini using retrieved context
7. Returns response in Portuguese with source attribution

## Acceptance criteria (WHEN / THEN / SHALL)

1. WHEN user sends a greeting (e.g., "Olá", "Oi") THEN system SHALL respond with a friendly greeting in Portuguese and describe what it can help with.
2. WHEN user asks a QA question about a known topic THEN system SHALL return an answer grounded in retrieved context with source dates.
3. WHEN user asks a question and no relevant results are found THEN system SHALL return "Não encontrei informações confiáveis sobre este tema." and NOT hallucinate.
4. WHEN user sends an out-of-scope message (e.g., "What is the capital of Japan?") THEN system SHALL politely decline and redirect to Grenoble/expat topics.
5. WHEN user sends feedback (👍 or 👎) THEN system SHALL log it with the message_id and acknowledge.
6. WHEN user sends an ambiguous question THEN system SHALL ask ONE clarifying question.
7. WHEN response latency exceeds 10 seconds THEN system SHALL return a partial answer with disclaimer.
8. WHEN Qdrant or OpenAI is unreachable THEN system SHALL return a structured error, not crash.

## Mandatory DS / GenAI requirements

### 1) Data contracts

**Inputs:**
```
ChatRequest:
  chat_id: str (required)
  message: str (required, 1-2000 chars)
  message_id: str (required)
```

**Outputs:**
```
ChatResponse:
  answer: str (required)
  sources: list[Source] (may be empty)
  intent: str (greeting | qa | feedback | out_of_scope)
  category: str | null
  confidence: float (0.0 - 1.0)
  trace_id: str (required)
```

**Validation rules:**
- Message must be 1–2000 characters
- Empty or whitespace-only messages → reject with error
- chat_id must be non-empty string

**Missing/invalid handling:**
- Invalid input → return structured error `{error_code: "INVALID_INPUT", message: "...", retryable: false}`
- Missing fields → fail-fast with 422

### 2) Grounding & evidence (anti-hallucination)

**Facts that MUST come from tools/data:**
- All factual answers about bureaucratic processes, addresses, links, timelines
- Any dates, deadlines, or procedural steps
- Official website URLs (ANEF, CAF, préfecture)

**Evidence fields required in outputs:**
- `sources`: list of `{text_snippet, date, category}` from Qdrant results
- `confidence`: float score based on retrieval quality

**Grounding rule:** If zero relevant chunks are retrieved (similarity < threshold), the system MUST return the no-results fallback. It MUST NOT generate an answer from LLM knowledge alone.

### 3) Safety & compliance

**Refusal / escalation rules:**
- Legal advice → "Para questões legais, consulte um advogado ou associação de apoio."
- Medical emergencies → "Em caso de emergência, ligue 15 (SAMU) ou 112."
- Out-of-scope → polite decline + redirect to supported topics

**Sensitive data handling:**
- No PII storage beyond Telegram chat_id (ephemeral)
- WhatsApp data is anonymized during ingestion (names removed)
- Logs do not contain user messages, only trace_id + intent + category

### 4) Quality metrics

**Offline metrics + targets:**
- Retrieval recall@5 ≥ 0.70 on eval set
- Answer relevance (LLM-as-judge) ≥ 0.80 on eval set

**Online metrics + targets:**
- User satisfaction (thumbs up rate) ≥ 85% in first month
- Latency p95 < 5 seconds

### 5) Latency/cost budget

**Latency targets:**
- p50: < 2 seconds
- p95: < 5 seconds
- Hard timeout: 10 seconds (return partial/fallback)

**Max tool calls per request:** 2 (1 classification, 1 search)
**Max LLM calls per request:** 3 (intent, category, synthesis)

**Timeouts:**
- Qdrant search: 3 seconds
- OpenAI call: 8 seconds
- Total request: 10 seconds

**Cost target:** < $5/month OpenAI for ~1000 queries/month

### 6) Failure modes + safe behavior

| Failure mode | Safe behavior |
|---|---|
| Ambiguous query | Ask 1 clarifying question |
| No results found | Return "Não encontrei informações confiáveis sobre este tema." |
| Tool timeout / error | Return partial retrieval answer with disclaimer |
| Unsafe / out-of-scope query | Politely decline and redirect |
| Low confidence answer | Provide best guess + suggest verifying with official source |
| Qdrant unreachable | Log error, return "Serviço temporariamente indisponível. Tente novamente em alguns minutos." |
| OpenAI unreachable | Log error, return "Não consegui processar sua pergunta. Tente novamente." |
| Rate limit exceeded | Return "Muitas perguntas em pouco tempo. Aguarde um momento." |

### 7) Observability

**trace_id requirement:**
- Every request gets a UUID trace_id at API entry
- trace_id propagated through all nodes, tools, and LLM calls

**Logs/metrics (minimum):**
- `request_received`: trace_id, chat_id, timestamp
- `intent_classified`: trace_id, intent, latency_ms
- `category_classified`: trace_id, category, latency_ms
- `search_completed`: trace_id, num_results, top_score, latency_ms
- `response_generated`: trace_id, confidence, total_latency_ms
- `tool_failure`: trace_id, tool_name, error_code, retryable
- `fallback_triggered`: trace_id, reason
- `feedback_received`: trace_id, message_id, rating

## Non-goals
- Building a general-purpose chatbot
- Supporting languages other than Portuguese
- Persistent conversation memory across sessions
- Automated content freshness detection
- Admin interface for knowledge management

## Assumptions
- Qdrant collection is pre-built via the ingestion pipeline (offline)
- The embedding model (`intfloat/multilingual-e5-small`) is loaded locally on the VPS
- OpenAI API is available and within budget
- Telegram Bot API is stable and free
- ~300 users, ~30-50 queries/day expected
