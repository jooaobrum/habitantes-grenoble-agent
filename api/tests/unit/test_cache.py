import time
from habitantes.domain.cache import SimpleResponseCache


def test_cache_hit_miss():
    cache = SimpleResponseCache(max_size=2, ttl_seconds=1)

    # Set item
    cache.set("query 1", "cat1", {"answer": "resp 1"})

    # Hit
    res = cache.get("query 1", "cat1")
    assert res == {"answer": "resp 1"}

    # Miss (different query)
    res = cache.get("query 2", "cat1")
    assert res is None

    # Miss (different category)
    res = cache.get("query 1", "cat2")
    assert res is None


def test_cache_expiry():
    cache = SimpleResponseCache(max_size=2, ttl_seconds=0.1)
    cache.set("query 1", "cat1", {"answer": "resp 1"})

    time.sleep(0.2)
    res = cache.get("query 1", "cat1")
    assert res is None


def test_cache_lru():
    cache = SimpleResponseCache(max_size=2, ttl_seconds=10)

    cache.set("q1", "c1", {"a": 1})
    cache.set("q2", "c1", {"a": 2})

    # Access q1 to make it most recently used
    cache.get("q1", "c1")

    # Set q3, should evict q2
    cache.set("q3", "c1", {"a": 3})

    assert cache.get("q1", "c1") is not None
    assert cache.get("q2", "c1") is None
    assert cache.get("q3", "c1") is not None


def test_normalization():
    cache = SimpleResponseCache(max_size=2, ttl_seconds=10)
    cache.set("  Query  ", "cat1", {"answer": "ok"})

    res = cache.get("query", "cat1")
    assert res == {"answer": "ok"}
