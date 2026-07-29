"""Tests for embedding provider expansion (v0.7.0). Split into two
groups: config-resolution tests for providers with no live key/instance
available (mistral, together, cohere, voyage) - no network calls, just
verifying defaults/env-fallback/error-raising logic - and real live
tests against a genuinely running local Ollama instance, skipped
automatically if Ollama isn't reachable so CI never fails on its
absence."""
import os
import pytest
from ragleap.embedding import EmbeddingConfig, EmbeddingService

ollama_available = True
try:
    import requests
    requests.get("http://localhost:11434/api/tags", timeout=1).raise_for_status()
except Exception:
    ollama_available = False


# --- Config-resolution tests (no network calls, no keys needed) ---

def test_mistral_default_model_and_dimensions():
    config = EmbeddingConfig(provider="mistral", api_key="fake-key")
    assert config.model == "mistral-embed"
    assert config.dimensions == 1024
    assert config.base_url == "https://api.mistral.ai/v1"


def test_together_requires_explicit_model_and_dimensions():
    with pytest.raises(ValueError, match="no safe default"):
        EmbeddingConfig(provider="together", api_key="fake-key")


def test_together_works_with_explicit_model_and_dimensions():
    config = EmbeddingConfig(provider="together", api_key="fake-key", model="some-model", dimensions=512)
    assert config.model == "some-model"
    assert config.dimensions == 512
    assert config.base_url == "https://api.together.xyz/v1"


def test_cohere_default_model_and_dimensions():
    config = EmbeddingConfig(provider="cohere", api_key="fake-key")
    assert config.model == "embed-english-v3.0"
    assert config.dimensions == 1024


def test_voyage_default_model_and_dimensions():
    config = EmbeddingConfig(provider="voyage", api_key="fake-key")
    assert config.model == "voyage-3"
    assert config.dimensions == 1024


def test_missing_api_key_raises_for_mistral():
    with pytest.raises(ValueError, match="No API key"):
        EmbeddingConfig(provider="mistral")


def test_missing_api_key_raises_for_cohere():
    with pytest.raises(ValueError, match="No API key"):
        EmbeddingConfig(provider="cohere")


def test_missing_api_key_raises_for_voyage():
    with pytest.raises(ValueError, match="No API key"):
        EmbeddingConfig(provider="voyage")


def test_ollama_needs_no_api_key():
    """Mirrors generation.py's existing ollama exemption from requiring
    an api_key - local inference, nothing to authenticate."""
    config = EmbeddingConfig(provider="ollama")
    assert config.api_key is None
    assert config.model == "nomic-embed-text"
    assert config.dimensions == 768
    assert config.base_url == "http://localhost:11434/v1"


def test_env_var_fallback_for_mistral(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "env-key")
    monkeypatch.setenv("MISTRAL_EMBEDDING_MODEL", "custom-mistral-model")
    config = EmbeddingConfig(provider="mistral")
    assert config.api_key == "env-key"
    assert config.model == "custom-mistral-model"


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        EmbeddingConfig(provider="not-a-real-provider", api_key="fake-key")


def test_explicit_dimensions_override_default():
    config = EmbeddingConfig(provider="cohere", api_key="fake-key", dimensions=256)
    assert config.dimensions == 256


# --- Live Ollama tests - skipped automatically if Ollama isn't running ---

pytestmark_ollama = pytest.mark.skipif(not ollama_available, reason="Ollama not running on localhost:11434")


@pytestmark_ollama
def test_ollama_embed_text_returns_real_vector():
    config = EmbeddingConfig(provider="ollama")
    service = EmbeddingService(config)
    vec = service.embed_text("This is a live test of the Ollama embedding path.")
    assert vec is not None
    assert len(vec) == 768
    assert all(isinstance(v, float) for v in vec)


@pytestmark_ollama
def test_ollama_embed_batch_returns_real_vectors():
    config = EmbeddingConfig(provider="ollama")
    service = EmbeddingService(config)
    batch = service.embed_batch(["first text", "second text", "third text"])
    assert len(batch) == 3
    assert all(v is not None and len(v) == 768 for v in batch)


@pytestmark_ollama
def test_ollama_embed_text_empty_string_returns_none():
    config = EmbeddingConfig(provider="ollama")
    service = EmbeddingService(config)
    assert service.embed_text("") is None
    assert service.embed_text("   ") is None


@pytestmark_ollama
def test_ollama_full_rag_integration_with_faiss(tmp_path, database_url):
    """Real end-to-end proof: Ollama embeds -> stored in a real FAISS
    index -> retrieved via real cosine similarity search. Uses FAISS
    (not the shared pgvector test DB) since Ollama's 768 dims don't
    match the test DB's deliberately-tiny vector(8) schema."""
    from ragleap import RagLeap, ProviderConfig, EmbeddingConfig as EC
    from ragleap.vectorstores import FAISSBackend

    backend = FAISSBackend(persist_directory=str(tmp_path / "ollama_faiss_data"))
    rag = RagLeap(
        database_url=database_url,
        embedder=EC(provider="ollama"),
        vector_backend=backend,
        primary=ProviderConfig(provider="gemini", api_key="fake-test-key"),
    )
    rag.init_schema()

    result = rag.ingest_text(
        "ollama_test.txt",
        "RagLeap uses Ollama for fully local, offline embeddings with no API key required.",
    )
    assert result.chunks_stored == 1

    query_embedding = rag._embed_query_cached("What does RagLeap use for local embeddings?")
    chunks = rag._vector_backend.search_dense(query_embedding, top_k=3)
    assert len(chunks) >= 1
    assert "Ollama" in chunks[0]["text"]
