import time
from habitantes.domain.cache import SimpleResponseCache


def test_cache_hit_miss():
    cache = SimpleResponseCache(max_size=2, ttl_seconds=1)

    # Set item
    cache.set("chat1", "query 1", "cat1", {"answer": "resp 1"})

    # Hit
    res = cache.get("chat1", "query 1", "cat1")
    assert res == {"answer": "resp 1"}

    # Miss (different query)
    res = cache.get("chat1", "query 2", "cat1")
    assert res is None

    # Miss (different category)
    res = cache.get("chat1", "query 1", "cat2")
    assert res is None


def test_cache_is_scoped_per_chat():
    """Answers depend on per-chat history — another chat must never get them."""
    cache = SimpleResponseCache(max_size=2, ttl_seconds=10)
    cache.set("chat1", "query 1", "cat1", {"answer": "resp 1"})

    assert cache.get("chat2", "query 1", "cat1") is None


def test_cache_expiry():
    cache = SimpleResponseCache(max_size=2, ttl_seconds=0.1)
    cache.set("chat1", "query 1", "cat1", {"answer": "resp 1"})

    time.sleep(0.2)
    res = cache.get("chat1", "query 1", "cat1")
    assert res is None


def test_cache_lru():
    cache = SimpleResponseCache(max_size=2, ttl_seconds=10)

    cache.set("chat1", "q1", "c1", {"a": 1})
    cache.set("chat1", "q2", "c1", {"a": 2})

    # Access q1 to make it most recently used
    cache.get("chat1", "q1", "c1")

    # Set q3, should evict q2
    cache.set("chat1", "q3", "c1", {"a": 3})

    assert cache.get("chat1", "q1", "c1") is not None
    assert cache.get("chat1", "q2", "c1") is None
    assert cache.get("chat1", "q3", "c1") is not None


def test_normalization():
    cache = SimpleResponseCache(max_size=2, ttl_seconds=10)
    cache.set("chat1", "  Query  ", "cat1", {"answer": "ok"})

    res = cache.get("chat1", "query", "cat1")
    assert res == {"answer": "ok"}
