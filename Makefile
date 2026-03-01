.PHONY: build up down logs run test lint eval help

# ── Docker management ───────────────────────────────────────────────────────
build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# ── Development (Local) ──────────────────────────────────────────────────────
# Note: Requires a local environment with dependencies installed (venv)
run-api:
	cd api && uvicorn habitantes.infrastructure.api.main:app --reload --host 0.0.0.0 --port 8000

run-bot:
	python app/telegram_bot.py

# ── Quality & Linting ────────────────────────────────────────────────────────
setup-hooks:
	pre-commit install

test:
	pytest tests/ -v

lint-format:
	pre-commit run --all-files

eval:
	python tests/eval/run_eval.py

# ── Help ───────────────────────────────────────────────────────────────────
help:
	@echo "Habitantes de Grenoble Chatbot — MVP Commands"
	@echo ""
	@echo "Docker:"
	@echo "  make up          Start all services"
	@echo "  make down        Stop all services"
	@echo "  make logs        Follow logs"
	@echo ""
	@echo "Local Dev (requires venv):"
	@echo "  make run-api     Run FastAPI service with reload"
	@echo "  make run-bot     Run Telegram bot"
	@echo ""
	@echo "Quality:"
	@echo "  make test         Run pytest suite"
	@echo "  make lint-format  Check quality (pre-commit)"
	@echo "  make setup-hooks  Install pre-commit hooks"
	@echo "  make eval         Run evaluation metrics"
