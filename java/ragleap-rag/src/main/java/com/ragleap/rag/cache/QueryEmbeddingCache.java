package com.ragleap.rag.cache;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.logging.Logger;

/**
 * Simple in-memory LRU cache for query embeddings.
 * Java port of ragleap-rag's cache.py — QueryEmbeddingCache.
 *
 * Does NOT cache full answers, only embeddings — an embedding is a pure
 * function of (text, model), so caching it is always safe, unlike
 * answer-level caching which could go stale with conversation memory.
 *
 * Note: this is the in-memory half of cache.py only. The Redis-backed
 * RedisQueryEmbeddingCache class in the Python source is NOT ported here —
 * it needs a live Redis client and real integration testing, scoped out
 * for now the same way db.py's ConnectionPool was.
 */
public class QueryEmbeddingCache {

    private static final Logger logger = Logger.getLogger(QueryEmbeddingCache.class.getName());

    private final int maxSize;
    private final LinkedHashMap<String, List<Double>> store;
    private long hits = 0;
    private long misses = 0;

    public QueryEmbeddingCache() {
        this(1000);
    }

    public QueryEmbeddingCache(int maxSize) {
        this.maxSize = maxSize;
        // accessOrder=true: both get() and put() move an entry to the end,
        // matching Python's explicit move_to_end() calls on hit and on set.
        this.store = new LinkedHashMap<>(16, 0.75f, true) {
            @Override
            protected boolean removeEldestEntry(Map.Entry<String, List<Double>> eldest) {
                boolean evict = size() > QueryEmbeddingCache.this.maxSize;
                if (evict) {
                    String key = eldest.getKey();
                    logger.fine(() -> "Cache full, evicted: "
                            + key.substring(0, Math.min(50, key.length())) + "...");
                }
                return evict;
            }
        };
    }

    private String key(String query, String model) {
        return model + ":" + query;
    }

    public Optional<List<Double>> get(String query, String model) {
        String k = key(query, model);
        List<Double> value = store.get(k); // accessOrder=true already moves it to MRU position
        if (value != null) {
            hits++;
            return Optional.of(value);
        }
        misses++;
        return Optional.empty();
    }

    public void set(String query, String model, List<Double> embedding) {
        String k = key(query, model);
        store.put(k, embedding); // accessOrder=true moves it to MRU; removeEldestEntry evicts LRU if over max
    }

    public void clear() {
        store.clear();
        hits = 0;
        misses = 0;
    }

    public CacheStats stats() {
        long total = hits + misses;
        double hitRate = total > 0 ? Math.round((double) hits / total * 10000.0) / 10000.0 : 0.0;
        return new CacheStats(hits, misses, hitRate, store.size());
    }

    public int getMaxSize() {
        return maxSize;
    }
}
