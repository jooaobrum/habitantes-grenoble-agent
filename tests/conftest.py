import os

import pytest

# Unit/integration tests mock every LLM + Qdrant call, but Settings still
# requires OPENROUTER_API_KEY (chat) + OPENAI_API_KEY (embeddings) to validate.
# Provide dummies so the suite is self-contained (no .env needed) and passes in
# CI where no keys are present.
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test-dummy")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
# ADMIN_TOKEN is required by Settings (Control Center); provide a dummy so the
# suite is self-contained and passes in CI where no real token is present.
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
# Alert email fields are env-only (never in yaml) and load_settings() reads a
# developer's real .env via load_dotenv(override=False). Pin them empty here
# so a developer's real SMTP credentials never leak into a test run and
# trigger a live send — tests that need SMTP config mock os.environ directly.
for _alerts_env_key in (
    "EMAIL_TO",
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_FROM",
    "SMTP_PASSWORD",
):
    os.environ.setdefault(_alerts_env_key, "")


@pytest.fixture(autouse=True)
def reset_response_cache():
    """Reset the global response-cache singleton between tests.

    Prevents cache hits from one test's fixture message leaking into
    another test that happens to reuse the same query text.
    """
    import habitantes.domain.cache as cache_module

    cache_module._cache = None
    yield
    cache_module._cache = None


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Reset the settings and derived category caches between tests.

    test_config patches yaml.safe_load and populates load_settings' lru_cache
    with a categories-less config; without a reset that leaks into later tests
    and makes the category-number shortcut resolve against an empty list.
    """
    from habitantes.config import load_settings
    import habitantes.domain.categories as categories_module

    load_settings.cache_clear()
    categories_module._categories_cache = None
    yield
    load_settings.cache_clear()
    categories_module._categories_cache = None
