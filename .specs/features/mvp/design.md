# MVP — DESIGN (HOW)

## Architecture

```
UI → API → Graph (LangGraph) → Tools
              ↑
            State (TypedDict)
Ingestion ───┘  (offline only, never at query time)
```

## State Definition

```python
class AgentState(TypedDict):
    """Typed state passed through the LangGraph graph."""
    # ── Request context ──
    chat_id: str
    message: str
    message_id: str
    trace_id: str

    # ── Classification ──
    intent: str          # greeting | qa | feedback | out_of_scope
    category: str        # visa | housing | healthcare | banking | transport | education | caf | general

    # ── Retrieval ──
    context_chunks: list[dict]   # [{text, source, date, category, score}]

    # ── Response ──
    answer: str
    sources: list[dict]          # [{text_snippet, date, category}]
    confidence: float

    # ── Memory ──
    history: list[dict]          # last 5 messages [{role, content}]

    # ── Observability ──
    timings: dict[str, float]    # {intent_ms, category_ms, search_ms, generation_ms}
    error: dict | None           # {error_code, message, retryable} or None
```

## Graph Structure

```
START
  │
  ▼
classify_intent
  │
  ├── intent == "greeting"      → generate_greeting → END
  ├── intent == "out_of_scope"  → generate_decline  → END
  ├── intent == "feedback"      → log_feedback       → END
  │
  ▼ (intent == "qa")
classify_category
  │
  ▼
route
  │
  ├── route == "clarify"   → generate_clarification → END
  │
  ▼ (route == "rag")
hybrid_search (Tool)
  │
  ▼
generate_response → END
```

## Node Signatures

Each node is a **pure function**: `(AgentState) → dict` (partial state update).

```python
def classify_intent(state: AgentState) -> dict:
    """Returns: {intent: str, timings: {...}}"""

def classify_category(state: AgentState) -> dict:
    """Returns: {category: str, timings: {...}}"""

def route(state: AgentState) -> str:
    """Conditional edge: returns 'rag' | 'clarify' | 'direct'"""

def generate_response(state: AgentState) -> dict:
    """Returns: {answer: str, sources: list, confidence: float, timings: {...}}"""

def generate_greeting(state: AgentState) -> dict:
    """Returns: {answer: str, confidence: 1.0}"""

def generate_decline(state: AgentState) -> dict:
    """Returns: {answer: str, confidence: 1.0}"""

def generate_clarification(state: AgentState) -> dict:
    """Returns: {answer: str, confidence: 0.5}"""

def log_feedback(state: AgentState) -> dict:
    """Returns: {answer: str}"""
```

## Tool Contracts

### hybrid_search

```python
# Input
query: str
category: str | None
top_k: int = 5

# Success output
{
    "chunks": [
        {
            "text": str,
            "question": str,
            "answer": str,
            "source": str,
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
        │   ├── agent.py               # LangGraph StateGraph
        │   ├── state.py               # AgentState TypedDict
        │   ├── nodes.py               # Pure function nodes
        │   ├── tools.py               # Thin wrapper tools
        │   ├── schemas.py             # Pydantic request/response models
        │   └── prompts/
        │       ├── __init__.py
        │       ├── intent.py          # Intent classification prompt
        │       ├── category.py        # Category classification prompt
        │       └── synthesis.py       # Answer synthesis prompt
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
│   └── test_schemas.py
├── integration/
│   └── test_agent_flow.py
└── eval/
    ├── run_eval.py
    └── cases/
        └── mvp_cases.json
```

## Ingestion (Offline, Already Built)

The ingestion pipeline is complete and separate from inference:
1. `0-wpp_parse_and_classify.py` — Parse WhatsApp export
2. `1-build_qa_pairs.py` — Extract Q&A pairs
3. `2-generate_synthesis_from_qa.py` — Generate synthesized answers
4. `3-build_qdrant_collection.py` — Build Qdrant collection (dense + sparse)

Collection: `qa_base` with dense (384d, E5-small) + sparse (BM25 hashing) vectors.

## Key Technical Decisions

| Component | Choice | Notes |
|-----------|--------|-------|
| Dense embedding | `intfloat/multilingual-e5-small` (384d) | Matches ingestion |
| Sparse embedding | BM25 hashing trick (262k dim) | Matches ingestion |
| Fusion | Reciprocal Rank Fusion (RRF) | Standard hybrid approach |
| Query prefix | `"query: "` (E5 convention) | Ingestion uses `"passage: "` |
| LLM | `gpt-4o-mini` | All classification + synthesis |
| Memory | In-memory dict, keyed by chat_id, max 5 msgs | Cleared on restart |
| Rate limiting | In-memory counter, 100 req/user/hour | Resets on restart |
