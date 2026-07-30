"""Tests for the in-memory query embedding cache — hit/miss tracking,
LRU eviction, disabled-cache behavior, and integration through ask()."""
from ragleap.cache import QueryEmbeddingCache


def test_cache_miss_then_hit():
    cache = QueryEmbeddingCache(max_size=10)
    assert cache.get("what is x?", "model-a") is None

    cache.set("what is x?", "model-a", [0.1, 0.2, 0.3])
    result = cache.get("what is x?", "model-a")
    assert result == [0.1, 0.2, 0.3]


def test_cache_key_includes_model():
    cache = QueryEmbeddingCache(max_size=10)
    cache.set("same query", "model-a", [0.1])
    assert cache.get("same query", "model-b") is None


def test_cache_stats_tracks_hits_and_misses():
    cache = QueryEmbeddingCache(max_size=10)
    cache.get("miss1", "m")
    cache.set("hit1", "m", [0.1])
    cache.get("hit1", "m")
    cache.get("hit1", "m")

    stats = cache.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["size"] == 1


def test_cache_evicts_least_recently_used_when_full():
    cache = QueryEmbeddingCache(max_size=2)
    cache.set("q1", "m", [1])
    cache.set("q2", "m", [2])
    cache.set("q3", "m", [3])  # should evict q1

    assert cache.get("q1", "m") is None
    assert cache.get("q2", "m") == [2]
    assert cache.get("q3", "m") == [3]


def test_cache_clear_resets_everything():
    cache = QueryEmbeddingCache(max_size=10)
    cache.set("q1", "m", [1])
    cache.get("q1", "m")
    cache.clear()

    assert cache.stats() == {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0}


def test_rag_cache_disabled_returns_zeroed_stats(database_url):
    from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
    from conftest import TEST_DIMENSIONS

    rag = RagLeap(
        database_url=database_url,
        embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
        cache_enabled=False,
    )
    assert rag.cache_stats() == {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "enabled": False}


def test_rag_ask_repeated_query_is_a_cache_hit(rag):
    rag.ingest_text(filename="a.txt", text="Some content about testing.")

    rag.ask("What is this about?")
    stats_after_first = rag.cache_stats()

    rag.ask("What is this about?")
    stats_after_second = rag.cache_stats()

    assert stats_after_first["misses"] == 1
    assert stats_after_second["hits"] == 1


def test_rag_cache_backend_redis_requires_redis_url(database_url):
    from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
    from conftest import TEST_DIMENSIONS
    import pytest

    with pytest.raises(ValueError, match="requires redis_url"):
        RagLeap(
            database_url=database_url,
            embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
            primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
            cache_backend="redis",
        )
