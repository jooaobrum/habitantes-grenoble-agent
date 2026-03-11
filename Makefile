.PHONY: build up down logs run test lint eval help

ENV ?= dev

# ── Docker management ───────────────────────────────────────────────────────
build:
	APP_ENV=$(ENV) docker compose build

up:
	APP_ENV=$(ENV) docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# ── Development (Local) ──────────────────────────────────────────────────────
# Note: Requires a local environment with dependencies installed (venv)
run-api:
	cd api && uvicorn habitantes.infrastructure.api.main:app --reload --host 0.0.0.0 --port 8000

run-bot:
	uv run python app/telegram_bot.py

ingest:
	PYTHONPATH=$$(pwd)/api/src uv run python ingestion/pipeline.py

load-only:
	PYTHONPATH=$$(pwd)/api/src uv run python ingestion/load_only.py
# ── Quality & Linting ────────────────────────────────────────────────────────
setup-hooks:
	pre-commit install

test:
	uv run pytest tests/ -v

lint-format:
	uv run pre-commit run --all-files

eval:
	uv run python tests/eval/run_eval.py

# ── Help ───────────────────────────────────────────────────────────────────
help:
	@echo "Habitantes de Grenoble Chatbot — MVP Commands"
	@echo ""
	@echo "Docker:"
	@echo "  make up            Start all services (default: dev)"
	@echo "  make up ENV=prod   Start all services in prod mode"
	@echo "  make down          Stop all services"
	@echo "  make logs          Follow logs"
	@echo ""
	@echo "Local Dev (requires venv):"
	@echo "  make run-api     Run FastAPI service with reload"
	@echo "  make run-bot     Run Telegram bot"
	@echo "  make ingest      Run the data ingestion pipeline"
	@echo ""
	@echo "Quality:"
	@echo "  make test         Run pytest suite"
	@echo "  make lint-format  Check quality (pre-commit)"
	@echo "  make setup-hooks  Install pre-commit hooks"
	@echo "  make eval         Run evaluation metrics"
