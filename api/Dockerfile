FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (no-dev for production-like image)
RUN uv sync --frozen --no-dev

# Copy source code and config
COPY api/src ./src
COPY config ./config

# Static admin dashboard (mounted at /admin/ui by main.py); lands at /app/admin,
# matching the repo-root-relative path main.py resolves in local/dev runs too.
COPY app/admin ./admin

# Add src to python path
ENV PYTHONPATH=/app/src

EXPOSE 8000

# Default command (can be overridden by docker-compose)
CMD ["/app/.venv/bin/uvicorn", "habitantes.infrastructure.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
