import os

import pytest

# Unit/integration tests mock every OpenAI + Qdrant call, but Settings still
# requires OPENAI_API_KEY to validate. Provide a dummy so the suite is
# self-contained (no .env needed) and passes in CI where no key is present.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")


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
