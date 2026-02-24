import time


class RagFlowCache:
    def __init__(self, ttl_seconds=300):
        self._cache = {}
        self._ttl = ttl_seconds

    def get(self, key):
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return data
            del self._cache[key]
        return None

    def set(self, key, data):
        self._cache[key] = (data, time.time())

    def invalidate(self, key):
        if key in self._cache:
            del self._cache[key]


ragflow_cache = RagFlowCache(ttl_seconds=300)
