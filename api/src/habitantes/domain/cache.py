import logging
import time
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SimpleResponseCache:
    """In-memory TTL+LRU cache for agent responses."""

    def __init__(self, max_size: int = 256, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()

    def _normalize_query(self, query: str) -> str:
        return query.strip().lower()

    def _get_key(self, query: str, category: str) -> str:
        return f"{self._normalize_query(query)}|{category}"

    def get(self, query: str, category: str) -> Optional[dict[str, Any]]:
        """Retrieve a cached response if it exists and is not expired."""
        key = self._get_key(query, category)
        if key not in self.cache:
            return None

        value, timestamp = self.cache[key]
        if (time.time() - timestamp) > self.ttl_seconds:
            logger.debug(f"Cache miss (TTL expired): {key}")
            del self.cache[key]
            return None

        # Move to end (LRU behavior)
        self.cache.move_to_end(key)
        logger.debug(f"Cache hit: {key}")
        return value

    def set(self, query: str, category: str, value: dict[str, Any]):
        """Store a response in the cache with the current timestamp."""
        key = self._get_key(query, category)
        if key in self.cache:
            del self.cache[key]

        if len(self.cache) >= self.max_size:
            # Remove oldest item
            self.cache.popitem(last=False)

        # Store a shallow copy to prevent external mutation issues
        self.cache[key] = (value.copy(), time.time())
        logger.debug(f"Cache set: {key}")


_cache: Optional[SimpleResponseCache] = None


def get_cache() -> Optional[SimpleResponseCache]:
    """Lazy factory for the singleton cache instance."""
    global _cache
    if _cache is None:
        try:
            from habitantes.config import load_settings

            settings = load_settings().cache
            if settings.enabled:
                _cache = SimpleResponseCache(
                    max_size=settings.max_size, ttl_seconds=settings.ttl_seconds
                )
        except Exception as e:
            logger.error(f"Failed to initialize cache: {e}")
            return None
    return _cache
