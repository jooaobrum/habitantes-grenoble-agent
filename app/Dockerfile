FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (no-dev)
RUN uv sync --frozen --no-dev

# Copy bot code, config, and parts of the API needed (like config.py)
COPY app ./app
COPY api/src/habitantes ./api/src/habitantes
COPY config ./config

# Add the API src to PYTHONPATH so bot can find the habitantes package
ENV PYTHONPATH=/app/api/src

# Run the bot using the venv created by uv
CMD ["uv", "run", "python", "app/telegram_bot.py"]
