package com.ragleap.rag.cache;

/**
 * Snapshot of cache hit/miss/size stats.
 * Java equivalent of the dict returned by QueryEmbeddingCache.stats() in cache.py.
 */
public record CacheStats(long hits, long misses, double hitRate, int size) {
}
