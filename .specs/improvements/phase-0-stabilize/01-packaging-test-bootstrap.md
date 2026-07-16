# P0-01 · Packaging + test bootstrap on fresh clone

**Phase:** 0 — Stabilize · **Priority:** P0 (blocks all other work) · **Audit:** P1-4

## Problem
On a fresh clone `import habitantes` fails inside the uv venv and pytest resolves to the system Python — `make test`, `make eval`, and `make run-api` all fail. Cause: no `[build-system]` in [pyproject.toml](../../../pyproject.toml), a fragile two-root `packages.find`, and dev tools never synced.

## Change
- Add `[build-system]` (setuptools or hatchling) with explicit packages: `api/src/habitantes`, `ingestion`.
- Move `pytest`, `black`, `isort`, `flake8`, `mypy` into a `[dependency-groups] dev` group (or keep the optional extra and document `uv sync --extra dev`).
- Add `[tool.pytest.ini_options]` with `pythonpath = ["api/src", "."]`.
- Verify `make test` and `make eval` no longer need the Makefile `PYTHONPATH` hack for unit tests.

## Done when
- [ ] Fresh clone: `uv sync --group dev && make test` collects and passes all unit tests.
- [ ] `uv run python -c "import habitantes"` succeeds.
- [ ] `pytest tests/unit api/tests -q` runs without `ModuleNotFoundError`.
