# Architecture - Brazilian Expats Chatbot MVP

## Overview

Knowledge-based chatbot serving Brazilian expats in Grenoble via Telegram. Handles ~100 users with 5-10 concurrent chats on a low-cost VPS (~$8-12/month).

## System Diagram

```mermaid
flowchart TD
    User([User])

    subgraph VPS["LOW-COST VPS (Hetzner/OVH)"]
        TG["Telegram Bot (long polling)<br>- Message deduplication<br>- Per-chat locks"]
        API["FastAPI Service<br>POST /chat<br>POST /feedback"]

        subgraph Agent["AGENT ORCHESTRATOR (ReAct Loop)"]
            Intent["1. Intent Classifier<br>- Greeting<br>- QA<br>- Feedback<br>- Out-of-scope"]
            Category["2. Category Classifier (if QA)<br>- Visa, Housing, etc."]
            Router["3. Router<br>- Direct<br>- RAG<br>- Clarify"]

            subgraph Tools["4. Tools"]
                Search["Hybrid Search Tool<br>Dense: SentenceTransformer<br>Sparse: BM25<br>Fusion: RRF (top-k=5)"]
            end

            Gen["5. Response Generator<br>- OpenAI synthesis<br>- Source attribution<br>- Confidence indicator"]
            Memory[/"Short-term Memory (MemoryState)<br>- Last 5 messages per chat"/]
        end

        DB[("Qdrant (Vector Store)<br>Collection: qa_base<br>- Dense/Sparse vectors<br>- Metadata")]
    end

    OAI["OpenAI API<br>- gpt-4o-mini"]

    User <-->|Chat| TG
    TG <--> API
    API <--> Intent
    Intent -->|QA| Category
    Category --> Router
    Router -->|RAG| Search
    Search --> Gen
    Gen --> Router

    Search <--> DB
    Gen <--> OAI
    Agent <--> Memory
```

## Key Flows

### 1. Chat Flow
```mermaid
flowchart TD
    User([User]) -->|Chat| TG[Telegram]
    TG --> API[FastAPI /chat]
    API --> Intent[Intent Classification]

    Intent -->|If QA| Cat[Category Classification]
    Cat --> Cache{Response Cache Check}
    Cache -->|Hit| Resp([Response])
    Cache -->|Miss| Router{Router Decision}

    Router -->|RAG Needed| Search[Hybrid Search + Category Filter]
    Search -->|Top 5 Results| Synth[OpenAI Synthesis with Context]
    Synth --> Resp

    Resp --> API
    API --> TG
    TG --> User
```

### 2. Retrieval Flow
```mermaid
flowchart TD
    Query([Query text])
    Query --> Dense[SentenceTransformer-PT]
    Query --> Sparse[BM25-PT]

    Dense -->|Dense vector 1024d| Fusion
    Sparse -->|Sparse vector| Fusion

    Fusion[Hybrid fusion RRF] --> DB[(Qdrant query)]
    DB --> TopK([Top-k results])
```

### 3. Feedback Flow (MVP Simplified)
```mermaid
flowchart LR
    User([User rating]) --> API[FastAPI /feedback]
    API --> Log[/Log to file/]
    Log -.-> Future[Future: aggregate metrics, quality tracking]
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
- **Validation**: Pydantic models (size limits enforced)
- **Rate limiting**: Settings-driven in-memory counter (defaults to 100/hr)

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
