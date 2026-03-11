# Habitantes de Grenoble — AI Chatbot

An AI-powered assistant that helps Brazilian expats in Grenoble navigate daily life, bureaucracy, and housing. The bot leverages 5 years of community knowledge from WhatsApp groups to provide instant, reliable, grounded answers in Portuguese.

---

## Architecture

```
Telegram Bot → FastAPI → LangGraph ReAct Agent → Qdrant (hybrid search)
                                                ↑
                              Ingestion pipeline (offline only)
```

- **Orchestration**: LangGraph ReAct loop with explicit intent routing
- **Backend**: FastAPI
- **Vector Store**: Qdrant with hybrid search (dense + sparse RRF fusion)
- **Client**: Telegram Bot (long-polling)
- **Config**: `config/base.yaml` + `.env` secrets + `APP_ENV` environment selector

---

## Prerequisites

- Python 3.12+
- Docker & Docker Compose
- `uv` (recommended) or `pip`
- OpenAI API Key
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))

---

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure secrets

```bash
cp .env.example .env
```

Edit `.env` and set:

```bash
OPENAI_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=...
```

`APP_ENV` defaults to `dev` — only set it explicitly if you want `prod`.

---

## Running the project

All commands go through `make`. The `ENV` variable controls which environment config is loaded from `config/base.yaml`.

### Environments

| Command | Effect |
|---|---|
| `make up` | Start all services in **dev** mode (default) |
| `make up ENV=prod` | Start all services in **prod** mode |
| `make build` | Build Docker images (dev) |
| `make build ENV=prod` | Build Docker images (prod) |
| `make down` | Stop all services |
| `make logs` | Follow live logs from all containers |

What changes between environments:

| Setting | `dev` | `prod` |
|---|---|---|
| `api.log_level` | `DEBUG` | `WARNING` |
| `api.eval_gate_enabled` | `false` | `true` |

To add more per-environment overrides, edit the `environments:` block in [config/base.yaml](config/base.yaml).

---

## Data ingestion

Ingestion is **offline only** — never runs at query time. It parses raw WhatsApp exports, synthesizes QA pairs via LLM, and loads vectors into Qdrant.

### Step 1 — Place the raw data

```
data/chat-19012021-20022026.txt   ← WhatsApp export file
```

### Step 2 — Full pipeline (parse → synthesize → load)

Runs all stages end-to-end and writes artifacts to `artifacts/<chat-stem>/`.

```bash
make ingest
```

### Step 3 — Load only (skip re-synthesis)

If synthesis artifacts already exist and you only need to re-index into Qdrant (e.g. after recreating the collection):

```bash
make load-only
```

Use `load-only` when:
- You dropped and recreated the Qdrant collection
- You changed embedding parameters and need to re-upsert existing vectors
- The LLM synthesis step is already done and you don't want to re-run it

---

## Full local workflow (step by step)

If you want to run services individually without Docker:

```bash
# 1. Start Qdrant only
docker compose up -d qdrant

# 2. Ingest data into Qdrant
make ingest          # full pipeline
# or
make load-only       # re-index existing artifacts

# 3. Start the API
make run-api         # FastAPI on http://localhost:8000

# 4. Start the Telegram bot
make run-bot
```

---

## Quality

```bash
make test            # Run pytest suite
make lint-format     # Run pre-commit hooks (black, isort, flake8)
make eval            # Run RAG evaluation pipeline
make setup-hooks     # Install pre-commit hooks (first time only)
```

The eval gate (`python tests/eval/run_eval.py`) must pass before any merge.

---

## Project structure

```
├── api/                     # FastAPI backend + domain logic
│   └── src/habitantes/
│       ├── domain/          # Agent, nodes, tools, prompts
│       ├── infrastructure/  # API routes, DB clients
│       └── config.py        # Pydantic Settings loader
├── app/                     # Telegram bot client
├── config/
│   └── base.yaml            # All tuning constants + env overrides
├── ingestion/               # Offline ETL pipeline
├── data/                    # Raw WhatsApp exports (gitignored)
├── artifacts/               # Ingestion outputs (gitignored)
├── infra/                   # Qdrant storage volume
└── tests/                   # Unit, integration, eval suites
```

---

## Deploying to a VPS (production)

### 1. Connect to the VPS

```bash
ssh root@<your-vps-ip>
```

### 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER
apt-get install -y docker-compose-plugin
# Log out and back in for group change to take effect
```

### 3. Secure the server

```bash
# Firewall — only allow SSH (no need to open 8000 or 6333)
ufw default deny incoming
ufw allow ssh
ufw enable
```

### 4. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env   # or start a new shell
```

### 5. Clone the repo and configure secrets

```bash
git clone https://github.com/jooaobrum/habitantes-grenoble-agent.git
cd habitantes-grenoble-agent
cp .env.example .env
nano .env          # fill OPENAI_API_KEY and TELEGRAM_BOT_TOKEN
chmod 600 .env
```

### 6. Install Python dependencies

```bash
uv sync
```

This creates a `.venv` from `pyproject.toml`. Required before running ingestion outside Docker.

### 7. Upload data and run ingestion

Transfer the gitignored data from your local machine:

```bash
# From your local machine
scp -r ./data ./artifacts root@<your-vps-ip>:/root/habitantes-grenoble-agent/
```

Then on the VPS, start Qdrant and load the vectors:

```bash
docker compose up -d qdrant

# If artifacts are already synthesized locally (recommended — skips OpenAI calls):
uv run python ingestion/load_only.py

# Or run the full pipeline from scratch (parses + synthesizes + loads):
uv run python ingestion/pipeline.py
```

Alternatively, if you want to reuse vectors already stored in Qdrant from a previous local run:

```bash
# From your local machine
scp -r ./infra/qdrant_storage root@<your-vps-ip>:/root/habitantes-grenoble-agent/infra/
```

### 8. Start the services

```bash
make up ENV=prod
# or directly:
APP_ENV=prod docker compose up -d --build
```

### 9. Verify everything is running

```bash
docker compose ps
docker compose logs -f
```

All three containers (`qdrant`, `api`, `telegram-bot`) should be healthy. The Telegram bot uses long-polling — no domain or reverse proxy needed.

### Updating the deployment

```bash
git pull origin main
APP_ENV=prod docker compose up -d --build
```

---

## Environment variables reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram bot token from @BotFather |
| `APP_ENV` | No | `dev` | Environment selector (`dev` or `prod`) |
| `QDRANT_URL` | No | `http://qdrant:6333` | Override Qdrant URL |
| `MODEL_NAME` | No | `gpt-4o-mini` | Override LLM model |
