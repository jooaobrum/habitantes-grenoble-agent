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

# Add src to python path
ENV PYTHONPATH=/app/src

EXPOSE 8000

# Default command (can be overridden by docker-compose)
CMD ["/app/.venv/bin/uvicorn", "habitantes.infrastructure.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
