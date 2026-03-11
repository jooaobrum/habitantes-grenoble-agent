# MVP — DESIGN (HOW)

## Architecture

```
UI → API → Cache → Agent (Two-Layer ReAct) → Tools
               ↑
             State (TypedDict)
Ingestion (ETL) ┘ (offline only, never at query time)
```

### Two-Layer ReAct Architecture

```
START
  │
  ▼
Layer 1: classify_intent (LLM classification)
  │
  │ Returns: {intent, category?, timings}
  │
  ▼
Cache Check (if QA intent)
  │
  │ Key: MD5(normalized_message + category)
  │ If HIT → Return cached ChatResponse
  │ If MISS → Proceed to Layer 2
  │
  ▼
Layer 2: ReAct Agent (LLM + tool calling loop)
  │
  │ Receives intent as context in system prompt
  │ Decides action:
  │   ├── greeting       → responds directly (no tool call)
  │   ├── out_of_scope   → declines politely (no tool call)
  │   ├── feedback       → acknowledges (no tool call)
  │   ├── qa + short msg → asks for clarification (no tool call)
  │   └── qa + long msg  → calls search_knowledge_base → synthesizes answer
  │
  │ Loop: LLM → tool_call? → execute tool → LLM → ... → final answer
  │ Max iterations: 5
  │ Max output tokens: 1024
  │
  ▼
Cache Update (if QA success)
  │
  ▼
END
```

## State Definition

```python
class AgentState(TypedDict):
    """Typed state passed through the agent."""
    # ── Request context ──
    chat_id: str
    message: str
    message_id: str
    trace_id: str

    # ── Classification ──
    intent: str          # greeting | qa | feedback | out_of_scope
    category: str        # e.g. "Visa & Residency"

    # ── Retrieval ──
    context_chunks: list[dict]   # [{text, source, date, category, score}]

    # ── Response ──
    answer: str
    sources: list[dict]          # [{text_snippet, date, category}]
    confidence: float

    # ── Memory ──
    history: list[dict]          # last 5 messages [{role, content}]

    # ── Observability ──
    timings: dict[str, float]    # {intent_ms, react_ms}
    error: dict | None           # {error_code, message, retryable} or None
```

## Agent Entry Point

```python
def run(chat_id: str, message: str, message_id: str, trace_id: str) -> dict:
    """Execute one agent turn end-to-end.

    Two-layer architecture:
      1. _classify_intent — determines intent
      2. _run_react_loop — ReAct loop with tool calling
    """
```

## Tool Contracts

### search_knowledge_base (LangChain tool)

```python
@tool
def search_knowledge_base(query: str, category: str = "") -> str:
    """Search the knowledge base for Brazilian expats in Grenoble.

    Args:
        query: Search query in Portuguese or French.
        category: Optional category filter.

    Returns:
        Formatted string with retrieved chunks, or error message.
    """
```

### hybrid_search (internal function)

```python
# Input
query: str
categories: list[str] | None
top_k: int = 5

# Success output
{
    "chunks": [
        {
            "text": str,
            "question": str,
            "answer": str,
            "source": str,
            "thread_id": int,
            "date": str,
            "category": str,
            "score": float
        }
    ]
}

# Error output
{
    "error": {
        "error_code": "QDRANT_TIMEOUT" | "QDRANT_UNREACHABLE" | "EMBEDDING_FAILURE",
        "message": str,
        "retryable": bool
    }
}
```

## API Contracts

### POST /chat

```python
# Request
class ChatRequest(BaseModel):
    chat_id: str
    message: str = Field(min_length=1, max_length=2000)
    message_id: str

# Response
class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    intent: str
    category: str | None
    confidence: float
    trace_id: str

class Source(BaseModel):
    text_snippet: str
    date: str
    category: str
```

### POST /feedback

```python
# Request
class FeedbackRequest(BaseModel):
    chat_id: str
    message_id: str
    rating: Literal["up", "down"]

# Response
class FeedbackResponse(BaseModel):
    status: str  # "ok"
```

### GET /health

```python
# Response
class HealthResponse(BaseModel):
    status: str   # "healthy"
    qdrant: str   # "connected" | "unreachable"
    version: str  # "0.1.0"
```

## Eval Pipeline

The evaluation pipeline validates retrieval quality and answer faithfulness before infrastructure work begins. It operates in 3 layers:

### Layer 1: Retrieval Metrics (offline, no LLM)

Pure functions that compare retrieved document IDs against golden expected IDs.

```python
def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int = 5) -> float:
    """Fraction of relevant docs found in top-k retrieved."""

def hit_rate_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int = 5) -> float:
    """1.0 if at least one relevant doc found in top-k, else 0.0."""

def context_precision(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    """Weighted precision: relevant docs ranked higher score more."""
```

### Layer 2: E2E Metrics (LLM-as-judge via OpenAI direct call)

Uses `openai.ChatCompletion.create()` directly (not LangChain) to keep eval independent from the agent framework.

```python
def answer_relevance(question: str, answer: str) -> float:
    """LLM judges if the answer addresses the question. Returns 0.0–1.0."""

def faithfulness(answer: str, context: list[str]) -> float:
    """LLM checks if every claim in the answer is supported by context. Returns 0.0–1.0."""

def semantic_similarity(answer: str, reference: str) -> float:
    """Cosine similarity between answer and reference embeddings. Returns 0.0–1.0."""
```

### Layer 3: Runner + CI Gate

```
python tests/eval/run_eval.py
  1. Loads golden_dataset.json
  2. For each case: runs retrieval → computes Layer 1 metrics
  3. For each case: runs generation → computes Layer 2 metrics
  4. Aggregates all metrics, compares against targets
  5. Writes tests/eval/report.json
  6. Exits 0 if ALL targets met, exits 1 otherwise
```

**Metric targets (gate):**

| Metric | Target |
|---|---|
| hit_rate@5 | ≥ 0.80 |
| recall@5 | ≥ 0.50 |
| context_precision | ≥ 0.50 |
| answer_relevance | ≥ 0.80 |
| faithfulness | ≥ 0.80 |
| semantic_similarity | ≥ 0.70 |

## File Map

```
api/
├── Dockerfile
├── pyproject.toml
└── src/
    └── habitantes/
        ├── __init__.py
        ├── config.py                  # Pydantic Settings
        │
        ├── domain/
        │   ├── __init__.py
        │   ├── agent.py               # Two-Layer ReAct Agent
        │   ├── state.py               # AgentState TypedDict
        │   ├── cache.py               # TTL + LRU response cache
        │   ├── tools/
        │   │   ├── __init__.py        # Public API only (4 exports)
        │   │   ├── search.py          # hybrid_search + LangChain tool
        │   │   ├── _ranking.py        # RRF + keyword ranking
        │   │   └── glossary.py        # Regional term mapping
        │   ├── schemas.py             # Pydantic models
        │   └── prompts/
        │       ├── __init__.py
        │       ├── intent.py          # Intent classification prompt
        │       ├── category.py        # Category classification prompt
        │       └── synthesis.py       # ReAct system prompt + answer synthesis
        │
        ├── eval/
        │   ├── __init__.py
        │   └── metrics.py             # recall_at_k, hit_rate_at_k,
        │                              # context_precision, answer_relevance,
        │                              # faithfulness, semantic_similarity
        │
        └── infrastructure/
            ├── __init__.py
            └── api/
                ├── __init__.py
                ├── main.py            # FastAPI app
                └── routers/
                    ├── __init__.py
                    ├── chat.py        # POST /chat
                    ├── feedback.py    # POST /feedback
                    └── health.py      # GET /health

app/
├── Dockerfile
├── requirements.txt
└── telegram_bot.py                    # Telegram long-polling bot

tests/
├── unit/
│   ├── test_nodes.py
│   ├── test_tools.py
│   ├── test_schemas.py
│   └── test_metrics.py                # Unit tests for eval metrics
├── integration/
│   └── test_agent_flow.py             # Integration tests for ReAct agent
└── eval/
    ├── run_eval.py                    # Eval runner + CI gate
    ├── golden_dataset.json            # 38 cases, ≥ 10 categories
    └── report.json                    # Generated by run_eval.py (gitignored)
```

## Ingestion (Modular ETL Package)

The ingestion pipeline is organized as a modular package with shared configuration from `base.yaml`.

### Structure
```
ingestion/
├── config.py           # Shared loader for ingestion settings
├── run.py              # CLI entry point (extract|preprocess|load)
├── extract/
│   ├── whatsapp_parser.py
│   └── qa_extractor.py
├── preprocess/
│   └── synthesis.py
└── load/
    └── qdrant_loader.py
```

### Strategy
- **Extract**: Parse WhatsApp exports → Classify Q&A pairs.
- **Preprocess**: Generate structured, synthesized answers using OpenAI.
- **Load**: Build Qdrant collection using hybrid vectors (Dense E5-large + Sparse BM25).

## Key Technical Decisions

| Component | Choice | Notes |
|-----------|--------|-------|
| Agent architecture | Two-Layer ReAct | Layer 1: intent, Layer 2: ReAct loop |
| Response Caching | In-memory LRU + TTL | TTL=1hr, max_size=256, normalized keys |
| Dense embedding | `intfloat/multilingual-e5-small` | Fast, high quality for PT |
| Sparse embedding | `fastembed` BM25 (Portuguese) | High-quality lexical matching |
| LLM | `gpt-4o-mini` | Max output tokens: 1024 |
| Rate limiting (API) | Settings-driven | Defaults to 100 req/user/hour |
| Rate limiting (Bot) | Sliding window | 10 messages/min per chat |
| Ingestion Config | Centralized base.yaml | Shared with API for consistency |
