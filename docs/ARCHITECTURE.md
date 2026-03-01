# Architecture - Brazilian Expats Chatbot MVP

## Overview

Knowledge-based chatbot serving Brazilian expats in Grenoble via Telegram. Handles ~100 users with 5-10 concurrent chats on a low-cost VPS (~$8-12/month).

## System Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                          LOW-COST VPS (Hetzner/OVH)                    │
│                                                                         │
│  ┌──────────┐         ┌─────────────────────────────────────────┐     │
│  │   User   │────────▶│  Telegram Bot (long polling)            │     │
│  └──────────┘         │  - Message deduplication                │     │
│                       │  - Per-chat locks                        │     │
│                       └────────────────┬────────────────────────┘     │
│                                        │                               │
│                       ┌────────────────▼────────────────────────┐     │
│                       │  FastAPI Service                         │     │
│                       │                                          │     │
│                       │  POST /chat                              │     │
│                       │  POST /feedback                          │     │
│                       └────────────────┬────────────────────────┘     │
│                                        │                               │
│  ┌─────────────────────────────────────▼────────────────────────────┐ │
│  │              AGENT ORCHESTRATOR (LangGraph)                       │ │
│  │                                                                   │ │
│  │  ┌──────────────────┐       ┌─────────────────┐                 │ │
│  │  │ 1. Intent        │──────▶│ 2. Category     │                 │ │
│  │  │    Classifier    │       │    Classifier   │                 │ │
│  │  │    - Greeting    │       │    (if QA)      │                 │ │
│  │  │    - QA          │       │    - Visa       │                 │ │
│  │  │    - Feedback    │       │    - Housing    │                 │ │
│  │  │    - Out-of-scope│       │    - Healthcare │                 │ │
│  │  └──────────────────┘       │    - Banking    │                 │ │
│  │                             │    - Transport  │                 │ │
│  │                             │    - Education  │                 │ │
│  │                             │    - General    │                 │ │
│  │                             └────────┬────────┘                 │ │
│  │                                      │                          │ │
│  │                             ┌────────▼────────┐                 │ │
│  │                             │ 3. Router       │                 │ │
│  │                             │    - Direct     │                 │ │
│  │                             │    - RAG        │                 │ │
│  │                             │    - Clarify    │                 │ │
│  │                             └────────┬────────┘                 │ │
│  │                                      │                          │ │
│  │  ┌───────────────────────────────────▼─────────┐                │ │
│  │  │  3. Tools                                   │                │ │
│  │  │                                             │                │ │
│  │  │  ┌──────────────────────────────┐           │                │ │
│  │  │  │  Hybrid Search Tool          │           │                │ │
│  │  │  │                              │           │                │ │
│  │  │  │  Dense: SentenceTransformer  │           │                │ │
│  │  │  │         (Portuguese)         │           │                │ │
│  │  │  │                              │           │                │ │
│  │  │  │  Sparse: BM25                │           │                │ │
│  │  │  │          (Portuguese)        │           │                │ │
│  │  │  │                              │           │                │ │
│  │  │  │  Fusion: RRF (top-k=5)      │──────┐    │                │ │
│  │  │  └──────────────────────────────┘      │    │                │ │
│  │  └──────────────────────────────────────────────┘                │ │
│  │                                            │                     │ │
│  │  ┌─────────────────────────────────────────▼──────┐              │ │
│  │  │  4. Response Generator                         │              │ │
│  │  │     - OpenAI synthesis (gpt-4o-mini)          │              │ │
│  │  │     - Source attribution                       │              │ │
│  │  │     - Confidence indicator                     │              │ │
│  │  └────────────────────────────────────────────────┘              │ │
│  │                                                                   │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │
│  │  │  Short-term Memory (MemoryState)                             │ │
│  │  │  - Last 5 messages per chat                                  │ │
│  │  │  - In-memory only (MVP)                                      │ │
│  │  └──────────────────────────────────────────────────────────────┘ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                        │                               │
│                       ┌────────────────▼────────────────────────┐     │
│                       │  Qdrant (Vector Store)                  │     │
│                       │                                          │     │
│                       │  Collection: qa_base                     │     │
│                       │  - Dense vectors (1024d)                 │     │
│                       │  - Sparse vectors (BM25)                 │     │
│                       │  - Metadata: source, date, category      │     │
│                       └──────────────────────────────────────────┘     │
│                                                                         │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                         ┌────────────▼───────────┐
                         │  OpenAI API            │
                         │  - gpt-4o-mini         │
                         │  - Text generation     │
                         └────────────────────────┘
```

## Key Flows

### 1. Chat Flow
```
User → Telegram → FastAPI /chat → Intent Classification
  ↓
If intent = QA:
  → Category Classification → Category tag (e.g., "visa", "housing")
  → Router Decision
  ↓
If RAG needed:
  → Hybrid Search (Dense + Sparse) + Category filter → Qdrant → Top 5 results
  → OpenAI synthesis with context → Response
  ↓
Response → FastAPI → Telegram → User
```

### 2. Retrieval Flow
```
Query text
  ↓
├─→ SentenceTransformer-PT → Dense vector (1024d)
│
└─→ BM25-PT → Sparse vector
  ↓
Hybrid fusion (RRF) → Qdrant query → Top-k results
```

### 3. Feedback Flow (MVP Simplified)
```
User rating → FastAPI /feedback → Log to file
(Future: aggregate metrics, quality tracking)
```

## Component Details

### 1. Telegram Bot Layer
- **Library**: `python-telegram-bot`
- **Mode**: Long polling (simpler than webhooks for MVP)
- **Concurrency**: Per-chat locks using `asyncio.Lock` dictionary
- **Idempotency**: Track processed `update_id` to prevent duplicates

### 2. FastAPI Service
- **Endpoints**:
  - `POST /chat`: Main conversation endpoint
  - `POST /feedback`: User ratings (thumbs up/down)
  - `GET /health`: Health check
- **Validation**: Pydantic models
- **Rate limiting**: Simple in-memory counter (100 req/user/hour)

### 3. Agent Orchestrator (LangGraph)
- **Graph structure**:
  ```
  START → Intent Classifier → Category Classifier → Router → [Search Tool] → Generator → END
  ```
- **State**: Custom `AgentState` with messages, context, intent, category
- **Memory**: `MemoryState` from langgraph (last 5 messages)

## Question Categories

When a message is classified as **QA intent**, it gets further categorized to improve retrieval and response quality.

### Category Taxonomy

| Category | Description | Examples |
|----------|-------------|----------|
| **visa** | Immigration, residence permits, work permits | "Como renovar titre de séjour?", "Preciso de visto para trabalhar?" |
| **housing** | Rent, accommodation, utilities | "Onde achar apartamento?", "Como funciona a caution?" |
| **healthcare** | Medical services, insurance, prescriptions | "Como marcar consulta?", "Onde fica o hospital?" |
| **banking** | Bank accounts, taxes, financial services | "Qual banco abrir conta?", "Como declarar imposto?" |
| **transport** | Public transit, bikes, car registration | "Como comprar passe de ônibus?", "Preciso carteira francesa?" |
| **education** | Schools, universities, childcare | "Como matricular filho na escola?", "Creches em Grenoble?" |
| **caf** | CAF benefits (APL, etc.) | "Como pedir APL?", "Documentos para CAF?" |
| **general** | Other daily life questions | "Onde comprar comida brasileira?", "Eventos brasileiros?" |

### Implementation

**Method**: Lightweight classification using OpenAI or local classifier

**OpenAI (MVP recommendation)**:
```python
prompt = f"""Classify this question into ONE category:
Categories: visa, housing, healthcare, banking, transport, education, caf, general

Question: {user_question}

Return only the category name."""
```

**Benefits**:
- ✅ More relevant results (housing questions → housing answers)
- ✅ Reduces cross-contamination (visa info in housing queries)
- ✅ Better analytics (track which topics are most asked)
- ✅ Enables category-specific prompts (future enhancement)

### Fallback Behavior

If category classifier is uncertain (confidence < 0.5):
- Use `category="general"`
- Search without category filter (broader search)
