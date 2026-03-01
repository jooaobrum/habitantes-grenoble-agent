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

#### 🐍 Running Locally
If you want to run services individually for development:
```bash
# Start Qdrant only
docker compose up -d qdrant

# Run API with live reload
make run-api

# Run Telegram Bot
make run-bot
```

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
