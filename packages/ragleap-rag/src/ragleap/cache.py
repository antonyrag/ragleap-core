"""
Query embedding cache for ragleap-rag.
Caches embeddings for repeated identical queries (e.g. an FAQ-style
bot getting the same question multiple times) to avoid a redundant
embedding API call. In-memory only, per RagLeap instance - no new
dependency, no external cache service required.

Deliberately does NOT cache full answers: with conversation memory,
identical questions can legitimately produce different answers
depending on session history, so answer-level caching risks returning
stale or wrong responses. Caching the embedding step is always safe,
since an embedding is a pure function of (text, model).
"""
import logging
from collections import OrderedDict
from typing import List, Optional

logger = logging.getLogger(__name__)


class QueryEmbeddingCache:
    """Simple in-memory LRU cache for query embeddings."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._store: OrderedDict[str, List[float]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def _key(self, query: str, model: str) -> str:
        return f"{model}:{query}"

    def get(self, query: str, model: str) -> Optional[List[float]]:
        key = self._key(query, model)
        if key in self._store:
            self._store.move_to_end(key)  # mark as recently used
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    def set(self, query: str, model: str, embedding: List[float]) -> None:
        key = self._key(query, model)
        self._store[key] = embedding
        self._store.move_to_end(key)
        if len(self._store) > self.max_size:
            evicted_key, _ = self._store.popitem(last=False)  # evict least recently used
            logger.debug(f"Cache full, evicted: {evicted_key[:50]}...")

    def clear(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict:
        total = self.hits + self.misses
        hit_rate = round(self.hits / total, 4) if total > 0 else 0.0
        return {"hits": self.hits, "misses": self.misses, "hit_rate": hit_rate, "size": len(self._store)}


class RedisQueryEmbeddingCache:
    """
    Redis-backed query embedding cache - same interface as
    QueryEmbeddingCache (get/set/clear/stats), so RagLeap can use
    either interchangeably. Unlike the in-memory cache, this survives
    process restarts and is shared across multiple worker processes
    or Celery workers, which was a real, named limitation of the
    in-memory-only cache. Requires the 'redis' extra:
    pip install ragleap-rag[redis]

    Note on stats: hits/misses are tracked per-instance (in-process
    counters), not shared across processes via Redis itself - each
    worker sees only its own hit/miss counts, even though the
    underlying cached embeddings ARE shared. This is a deliberate
    simplification, not an oversight - a fully distributed hit-rate
    counter would need its own Redis key with atomic increments,
    which adds complexity for a metric that is mainly useful for
    local debugging anyway.
    """

    def __init__(self, redis_url: str, max_size: int = 1000, ttl_seconds: int = 86400, key_prefix: str = "ragleap:embcache:"):
        try:
            import redis
        except ImportError as e:
            raise ValueError("Redis caching requires the 'redis' extra — pip install ragleap-rag[redis]") from e

        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix
        self._client = redis.Redis.from_url(redis_url, decode_responses=False)
        self.hits = 0
        self.misses = 0

    def _key(self, query: str, model: str) -> str:
        return f"{self.key_prefix}{model}:{query}"

    def get(self, query: str, model: str) -> Optional[List[float]]:
        import json
        key = self._key(query, model)
        raw = self._client.get(key)
        if raw is not None:
            self.hits += 1
            return json.loads(raw)
        self.misses += 1
        return None

    def set(self, query: str, model: str, embedding: List[float]) -> None:
        import json
        key = self._key(query, model)
        self._client.set(key, json.dumps(embedding), ex=self.ttl_seconds)

    def clear(self) -> None:
        cursor = 0
        while True:
            cursor, keys = self._client.scan(cursor=cursor, match=f"{self.key_prefix}*", count=500)
            if keys:
                self._client.delete(*keys)
            if cursor == 0:
                break
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict:
        total = self.hits + self.misses
        hit_rate = round(self.hits / total, 4) if total > 0 else 0.0
        size = 0
        cursor = 0
        while True:
            cursor, keys = self._client.scan(cursor=cursor, match=f"{self.key_prefix}*", count=500)
            size += len(keys)
            if cursor == 0:
                break
        return {"hits": self.hits, "misses": self.misses, "hit_rate": hit_rate, "size": size}
