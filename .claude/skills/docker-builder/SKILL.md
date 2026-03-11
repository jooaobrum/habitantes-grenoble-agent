---
name: docker-builder
version: "1.0"
last_reviewed: "2025-01"
description: Generate Dockerfiles and docker-compose for local dev of Python agent systems (FastAPI API + optional Streamlit UI + optional ingestion job). Includes patterns for private dependency access using BuildKit SSH mount or token secrets. Use when containerizing the project for local development/testing. Not for Kubernetes/production infra.
---

# Docker Builder (Python: FastAPI + Streamlit) — Lightweight

## Goals
- Local dev containers that mirror the **standard worktree**
- Fast rebuilds (layer caching)
- Secure handling of private dependencies (no secrets baked into images)

## Target services (minimal)
- `api`: FastAPI service (POST /ask, POST /feedback)
- `ui`: Streamlit UI (optional)
- `ingestion`: one-off job (optional)

## Private dependency access (choose one)
### A) BuildKit SSH (recommended)
- Use SSH agent forwarding so `pip install git+ssh://...` works
- No secrets stored in image layers

### B) Token secret (HTTPS)
- Use runtime env vars or BuildKit secrets
- Never hardcode tokens in Dockerfile

## Deliverables
- `docker/Dockerfile.api`
- `docker/Dockerfile.ui` (if Streamlit)
- `docker/Dockerfile.ingestion` (optional)
- `docker/docker-compose.yml`
- `.dockerignore`
- `.env.example` additions (ports, APP_ENV, secrets placeholders)

## Output format (mandatory)
- Files created/updated
- How to build/run commands
- Notes on private repo access chosen
- Troubleshooting checklist
