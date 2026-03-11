---
name: python-dev
version: "1.0"
last_reviewed: "2025-01"
description: Python development guidance for DS/agentic repos. Use when writing/reviewing/modifying Python code (.py) or notebooks. Emphasizes type hints, tests, structured errors, and simple maintainable code.
---

# Python Dev (Lightweight)

## Code quality
- Prefer simple, readable solutions.
- Small functions, single responsibility.
- Type hints for all public functions.
- Docstrings for non-trivial functions (Google style is fine).

## Errors
- Validate inputs early.
- Raise/catch specific exceptions (no bare except).
- Return structured error objects when crossing tool/API boundaries.

## Tests (critical)
- Use pytest.
- Add tests for new/changed behavior.
- Tests live in ./tests/.

## Environment
- Prefer `uv` or a `.venv`.
- Don’t create a new venv if `.venv` already exists.
- Lint/format with Ruff if configured.
