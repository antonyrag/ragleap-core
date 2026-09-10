package com.ragleap.rag.cache;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

class QueryEmbeddingCacheTest {

    @Test
    void defaultMaxSizeIsOneThousand() {
        assertEquals(1000, new QueryEmbeddingCache().getMaxSize());
    }

    @Test
    void missOnEmptyCache() {
        QueryEmbeddingCache cache = new QueryEmbeddingCache();
        assertTrue(cache.get("hello", "text-embedding-3-small").isEmpty());
        assertEquals(1, cache.stats().misses());
        assertEquals(0, cache.stats().hits());
    }

    @Test
    void hitAfterSet() {
        QueryEmbeddingCache cache = new QueryEmbeddingCache();
        List<Double> embedding = List.of(0.1, 0.2, 0.3);
        cache.set("hello", "text-embedding-3-small", embedding);

        Optional<List<Double>> result = cache.get("hello", "text-embedding-3-small");
        assertTrue(result.isPresent());
        assertEquals(embedding, result.get());
        assertEquals(1, cache.stats().hits());
        assertEquals(0, cache.stats().misses());
    }

    @Test
    void sameQueryDifferentModelsAreDistinctKeys() {
        QueryEmbeddingCache cache = new QueryEmbeddingCache();
        cache.set("hello", "model-a", List.of(1.0));
        assertTrue(cache.get("hello", "model-b").isEmpty());
    }

    @Test
    void evictsLeastRecentlyUsedWhenOverCapacity() {
        QueryEmbeddingCache cache = new QueryEmbeddingCache(2);
        cache.set("q1", "m", List.of(1.0));
        cache.set("q2", "m", List.of(2.0));
        cache.set("q3", "m", List.of(3.0)); // should evict q1 (least recently used)

        assertTrue(cache.get("q1", "m").isEmpty());
        assertTrue(cache.get("q2", "m").isPresent());
        assertTrue(cache.get("q3", "m").isPresent());
        assertEquals(2, cache.stats().size());
    }

    @Test
    void getRefreshesRecencyAndProtectsFromEviction() {
        QueryEmbeddingCache cache = new QueryEmbeddingCache(2);
        cache.set("q1", "m", List.of(1.0));
        cache.set("q2", "m", List.of(2.0));

        cache.get("q1", "m"); // q1 becomes most-recently-used; q2 becomes LRU

        cache.set("q3", "m", List.of(3.0)); // should evict q2, not q1

        assertTrue(cache.get("q1", "m").isPresent());
        assertTrue(cache.get("q2", "m").isEmpty());
        assertTrue(cache.get("q3", "m").isPresent());
    }

    @Test
    void clearResetsStoreAndCounters() {
        QueryEmbeddingCache cache = new QueryEmbeddingCache();
        cache.set("q1", "m", List.of(1.0));
        cache.get("q1", "m");
        cache.get("missing", "m");

        cache.clear();

        CacheStats stats = cache.stats();
        assertEquals(0, stats.hits());
        assertEquals(0, stats.misses());
        assertEquals(0, stats.size());
        assertTrue(cache.get("q1", "m").isEmpty());
    }

    @Test
    void hitRateIsZeroWithNoRequests() {
        assertEquals(0.0, new QueryEmbeddingCache().stats().hitRate());
    }

    @Test
    void hitRateComputedCorrectly() {
        QueryEmbeddingCache cache = new QueryEmbeddingCache();
        cache.set("q1", "m", List.of(1.0));
        cache.get("q1", "m");  // hit
        cache.get("q1", "m");  // hit
        cache.get("q2", "m");  // miss

        CacheStats stats = cache.stats();
        assertEquals(2, stats.hits());
        assertEquals(1, stats.misses());
        assertEquals(0.6667, stats.hitRate());
    }

    @Test
    void statsSizeReflectsStoreSize() {
        QueryEmbeddingCache cache = new QueryEmbeddingCache();
        cache.set("q1", "m", List.of(1.0));
        cache.set("q2", "m", List.of(2.0));
        assertEquals(2, cache.stats().size());
    }
}
