# 🏔️ Habitantes de Grenoble — AI Chatbot

An AI-powered assistant designed to help Brazilian expats in Grenoble, France, navigate daily life, bureaucracy, and housing. The bot leverages 5 years of community knowledge from WhatsApp groups to provide instant, reliable, and grounded answers in Portuguese.

## 🚀 Overview

The **Habitantes de Grenoble** bot acts as a centralized knowledge hub. Instead of searching through years of fragmented chat logs, users can ask questions directly on Telegram and receive answers backed by community experience.

### Key Features (MVP)
- **Instant Q&A**: Answers in Portuguese about visas, CAF, healthcare, banking, and more.
- **Grounded Responses**: Every answer is synthesized from real community discussions with source attribution.
- **Hybrid Search**: Combines semantic (dense) and keyword (sparse) search via Qdrant for maximum precision.
- **Smart Routing**: Classifies intents (Greeting, Q&A, Feedback, Out-of-scope) for efficient processing.
- **Feedback Loop**: Simple thumbs up/down to improve the knowledge base over time.

---

## 🏗️ Architecture

The system is built as a distributed agentic service:

- **Orchestration**: [LangGraph](https://github.com/langchain-ai/langgraph) for explicit workflow and state management.
- **Backend API**: [FastAPI](https://fastapi.tiangolo.com/) serving as the core intelligence layer.
- **Vector Store**: [Qdrant](https://qdrant.tech/) with Hybrid Search (dense + sparse RRF fusion).
- **Client Interface**: Telegram Bot (via `python-telegram-bot`).
- **Data Pipeline**: Custom ingestion scripts for parsing, synthesizing, and indexing WhatsApp data.

---

## 🛠️ Setup & Installation

### Prerequisites
- **Python 3.10+**
- **Docker & Docker Compose**
- **uv** (recommended for fast dependency management) or `pip`
- **OpenAI API Key** (for `gpt-4o-mini`)
- **Telegram Bot Token** (from [@BotFather](https://t.me/botfather))

### 1. Installation
Clone the repository and install dependencies:
```bash
# Clone
git clone https://github.com/jooaobrum/habitantes-grenoble-agent.git
cd habitantes-grenoble-agent

# Install with uv (recommended)
uv sync
uv pip install -e .

# Or using standard pip
pip install -e .
```

### 2. Configuration
Create a `.env` file from the example:
```bash
cp .env.example .env
```
Update the `.env` with your `OPENAI_API_KEY` and `TELEGRAM_BOT_TOKEN`.

### 3. Running the Project

#### 🐳 Using Docker (Recommended)
This starts the FastAPI service, Qdrant, and the Telegram bot in one go:
```bash
make up
```

#### 🐍 Running Locally (Manual Development)
If you want to run services individually for development:

1. **Start Qdrant**:
   ```bash
   docker compose up -d qdrant
   ```

2. **Ingest Data**:
   The ingestion pipeline automatically parses WhatsApp logs, aggregates QA pairs, synthesizes knowledge via LLM, and populates Qdrant:
   ```bash
   # 1. Put WhatsApp export in data/chat-19012021-20022026.txt
   # 2. Run the full unified pipeline:
   make ingest
   ```
   Processed artifacts (classified chats, QA JSONs, and synthesis results) will be grouped in `artifacts/<chat-filename-stem>/`.

3. **Run API**:
   ```bash
   make run-api
   ```

4. **Run Telegram Bot**:
   ```bash
   make run-bot
   ```

---

## 🤝 Onboarding for New Contributors

Welcome to the team! Here's how to navigate the codebase efficiently:

### 💡 Core Concepts
*   **Agent Orquestration**: We use a ReAct pattern (Reasoning + Acting). The agent first classifies the **Intent**, then selects a **Category**, and finally searches the KB to synthesize an answer.
*   **Domain-Driven**: The business logic lives in `api/src/habitantes/domain`. Infrastructure concerns (API routes, database clients) are in `infrastructure/`.
*   **Hybrid Search**: We use RRF (Reciprocal Rank Fusion) to combine Dense (semantic) and Sparse (keyword) results from Qdrant.

### 🔐 Environment Variables
You must define these in your `.env`:
*   `OPENAI_API_KEY`: Required for LLM usage.
*   `TELEGRAM_BOT_TOKEN`: Get this from @BotFather.
*   `APP_ENV`: `dev` (default) or `prod`.

### 🔄 Standard Workflow
1.  **Draft**: Modify logic in `domain/`.
2.  **Verify**: Run `make test` to ensure no regressions.
3.  **Hardening**: Ensure any new tuning parameters are added to `config/base.yaml` and not hardcoded.
4.  **Lint**: Run `make lint-format` before committing.

---

## 📁 Project Structure

```text
├── api/                     # Core Backend Service
│   └── src/habitantes/      # Domain logic, agents, and configs
├── app/                     # Client Interfaces (Telegram Bot)
├── config/                  # Configuration (YAML defaults per environment)
├── data/                    # Raw data (gitignored)
├── docs/                    # Architectural & Product documentation
├── ingestion/               # Offline data processing pipeline
├── infra/                   # Infrastructure config (Qdrant storage)
└── tests/                   # Unit, Integration, and Eval suites
```

---

## 🧪 Development & Quality

We use a `Makefile` to standardize common tasks:

- **Test**: `make test` — Runs the unit test suite.
- **Lint**: `make lint` — Checks code style (Black, Isort, Flake8).
- **Format**: `make format` — Auto-formats the codebase.
- **Eval**: `make eval` — Runs the RAG evaluation pipeline.
