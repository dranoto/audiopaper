import time
from functools import lru_cache
from typing import Any, Callable, Optional
import hashlib
import json


class SimpleCache:
    """Simple in-memory cache with TTL support."""

    def __init__(self, default_ttl: int = 300):
        self._cache = {}
        self._ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in cache with optional custom TTL."""
        if ttl is None:
            ttl = self._ttl
        self._cache[key] = (value, time.time())

    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def get_or_compute(
        self, key: str, compute_fn: Callable[[], Any], ttl: Optional[int] = None
    ) -> Any:
        """Get from cache or compute and store."""
        value = self.get(key)
        if value is not None:
            return value

        value = compute_fn()
        self.set(key, value, ttl)
        return value

    def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all keys starting with prefix."""
        keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
        for key in keys_to_delete:
            del self._cache[key]
        return len(keys_to_delete)


# Global cache instance
cache = SimpleCache(default_ttl=300)


def cache_key(*args, **kwargs) -> str:
    """Generate a cache key from arguments."""
    key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    return hashlib.md5(key_data.encode()).hexdigest()


def cached(ttl: int = 300, key_prefix: str = ""):
    """Decorator for caching function results."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            cache_key_val = f"{key_prefix}:{func.__name__}:{cache_key(*args, **kwargs)}"
            cached_value = cache.get(cache_key_val)
            if cached_value is not None:
                return cached_value

            result = func(*args, **kwargs)
            cache.set(cache_key_val, result, ttl)
            return result

        return wrapper

    return decorator


def invalidate_file_cache(file_id: int) -> None:
    """Invalidate all cache entries related to a file."""
    cache.invalidate_prefix(f"file:{file_id}")
    cache.delete(f"file_content:{file_id}")
    cache.delete(f"file_details:{file_id}")


def invalidate_chat_cache(file_id: int) -> None:
    """Invalidate chat-related cache for a file."""
    cache.invalidate_prefix(f"chat:{file_id}")
    cache.delete(f"chat_context:{file_id}")
