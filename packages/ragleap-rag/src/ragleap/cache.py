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
