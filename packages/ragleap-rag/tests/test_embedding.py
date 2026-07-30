"""Tests for embedding provider expansion (v0.7.0), updated for v0.9.0's
removal of all hardcoded model/dimension defaults - every provider now
requires explicit model= and dimensions= (constructor arg or env var),
matching the precedent "together" always set. Split into two groups:
config-resolution tests (no network calls, no keys needed beyond fakes)
and real live tests against a genuinely running local Ollama instance,
skipped automatically if Ollama isn't reachable so CI never fails on
its absence."""
import os
import pytest
from ragleap.embedding import EmbeddingConfig, EmbeddingService

# Captured before conftest.py's autouse fake_embedder fixture monkeypatches
# EmbeddingService.embed_text/embed_batch for every test in the suite - lets
# the dispatch test below temporarily restore real behavior for one test.
_REAL_EMBED_TEXT = EmbeddingService.embed_text

ollama_available = True
try:
    import requests
    requests.get("http://localhost:11434/api/tags", timeout=1).raise_for_status()
except Exception:
    ollama_available = False


# --- Config-resolution tests: explicit model=/dimensions= now mandatory ---

def test_mistral_requires_explicit_model_and_dimensions():
    with pytest.raises(ValueError, match="No embedding model specified"):
        EmbeddingConfig(provider="mistral", api_key="fake-key")


def test_mistral_works_with_explicit_model_and_dimensions():
    config = EmbeddingConfig(provider="mistral", api_key="fake-key", model="mistral-embed", dimensions=1024)
    assert config.model == "mistral-embed"
    assert config.dimensions == 1024
    assert config.base_url == "https://api.mistral.ai/v1"


def test_together_requires_explicit_model_and_dimensions():
    with pytest.raises(ValueError, match="No embedding model specified"):
        EmbeddingConfig(provider="together", api_key="fake-key")


def test_together_works_with_explicit_model_and_dimensions():
    config = EmbeddingConfig(provider="together", api_key="fake-key", model="some-model", dimensions=512)
    assert config.model == "some-model"
    assert config.dimensions == 512
    assert config.base_url == "https://api.together.xyz/v1"


def test_cohere_requires_explicit_model_and_dimensions():
    with pytest.raises(ValueError, match="No embedding model specified"):
        EmbeddingConfig(provider="cohere", api_key="fake-key")


def test_cohere_works_with_explicit_model_and_dimensions():
    config = EmbeddingConfig(provider="cohere", api_key="fake-key", model="embed-english-v3.0", dimensions=1024)
    assert config.model == "embed-english-v3.0"
    assert config.dimensions == 1024


def test_voyage_requires_explicit_model_and_dimensions():
    with pytest.raises(ValueError, match="No embedding model specified"):
        EmbeddingConfig(provider="voyage", api_key="fake-key")


def test_voyage_works_with_explicit_model_and_dimensions():
    config = EmbeddingConfig(provider="voyage", api_key="fake-key", model="voyage-3", dimensions=1024)
    assert config.model == "voyage-3"
    assert config.dimensions == 1024


def test_missing_api_key_raises_for_mistral():
    with pytest.raises(ValueError, match="No API key"):
        EmbeddingConfig(provider="mistral", model="mistral-embed", dimensions=1024)


def test_missing_api_key_raises_for_cohere():
    with pytest.raises(ValueError, match="No API key"):
        EmbeddingConfig(provider="cohere", model="embed-english-v3.0", dimensions=1024)


def test_missing_api_key_raises_for_voyage():
    with pytest.raises(ValueError, match="No API key"):
        EmbeddingConfig(provider="voyage", model="voyage-3", dimensions=1024)


def test_missing_model_raises_even_with_valid_api_key():
    """The core of the v0.9.0 change - having an API key isn't enough,
    model= (and dimensions=) are always required regardless of provider."""
    with pytest.raises(ValueError, match="No embedding model specified"):
        EmbeddingConfig(provider="cohere", api_key="real-looking-key")


def test_missing_dimensions_raises_even_with_model_specified():
    with pytest.raises(ValueError, match="No dimensions specified"):
        EmbeddingConfig(provider="cohere", api_key="fake-key", model="embed-english-v3.0")


def test_ollama_needs_no_api_key_but_still_needs_model_and_dimensions():
    """Mirrors generation.py's existing ollama exemption from requiring
    an api_key - local inference, nothing to authenticate. But model=
    and dimensions= are still mandatory - no provider is exempt from
    that, ollama included."""
    with pytest.raises(ValueError, match="No embedding model specified"):
        EmbeddingConfig(provider="ollama")

    config = EmbeddingConfig(provider="ollama", model="nomic-embed-text", dimensions=768)
    assert config.api_key is None
    assert config.model == "nomic-embed-text"
    assert config.dimensions == 768
    assert config.base_url == "http://localhost:11434/v1"


def test_env_var_fallback_for_mistral(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "env-key")
    monkeypatch.setenv("MISTRAL_EMBEDDING_MODEL", "custom-mistral-model")
    monkeypatch.setenv("MISTRAL_EMBEDDING_DIMENSIONS", "1024")
    config = EmbeddingConfig(provider="mistral")
    assert config.api_key == "env-key"
    assert config.model == "custom-mistral-model"
    assert config.dimensions == 1024


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        EmbeddingConfig(provider="not-a-real-provider", api_key="fake-key", model="whatever", dimensions=100)


def test_explicit_dimensions_always_required_no_override_concept():
    """There's no "default to override" anymore - dimensions must always
    be passed explicitly one way or another."""
    config = EmbeddingConfig(provider="cohere", api_key="fake-key", model="embed-english-v3.0", dimensions=256)
    assert config.dimensions == 256


def test_custom_provider_requires_base_url():
    with pytest.raises(ValueError, match="No base_url for provider 'custom'"):
        EmbeddingConfig(provider="custom", api_key="fake-key", model="some-model", dimensions=512)


def test_custom_provider_works_with_all_fields_explicit():
    """Proves the escape hatch this session was about: any OpenAI-
    compatible embeddings endpoint not otherwise named - a self-hosted
    server, or a provider without dedicated code (many Chinese providers
    - Qwen/DashScope, Zhipu/GLM, Moonshot/Kimi - ship OpenAI-compatible
    modes and work via this path today)."""
    config = EmbeddingConfig(
        provider="custom",
        api_key="fake-key",
        model="some-chinese-provider-embedding-model",
        dimensions=1024,
        base_url="https://api.some-provider.example.com/v1",
    )
    assert config.base_url == "https://api.some-provider.example.com/v1"
    assert config.model == "some-chinese-provider-embedding-model"
    assert config.dimensions == 1024


def test_custom_provider_env_var_fallback(monkeypatch):
    monkeypatch.setenv("CUSTOM_EMBEDDING_API_KEY", "env-key")
    monkeypatch.setenv("CUSTOM_EMBEDDING_MODEL", "env-model")
    monkeypatch.setenv("CUSTOM_EMBEDDING_DIMENSIONS", "512")
    monkeypatch.setenv("CUSTOM_EMBEDDING_BASE_URL", "https://env-configured.example.com/v1")
    config = EmbeddingConfig(provider="custom")
    assert config.api_key == "env-key"
    assert config.model == "env-model"
    assert config.dimensions == 512
    assert config.base_url == "https://env-configured.example.com/v1"


def test_custom_provider_dispatches_to_openai_compatible_path(monkeypatch):
    """Confirms EmbeddingService actually routes provider="custom" through
    the same _embed_openai_compatible code path as openai/mistral/etc,
    not treating it as an unknown/unhandled provider that silently
    returns None. Restores the real embed_text() for this one test,
    since conftest.py's autouse fake_embedder fixture globally fakes it
    for the whole suite - without restoring it, this test would call the
    fake version and never actually exercise the real dispatch logic."""
    from unittest.mock import patch

    monkeypatch.setattr(EmbeddingService, "embed_text", _REAL_EMBED_TEXT)

    config = EmbeddingConfig(
        provider="custom", api_key="fake-key", model="test-model",
        dimensions=4, base_url="https://fake.example.com/v1",
    )
    service = EmbeddingService(config)

    with patch.object(EmbeddingService, "_embed_openai_compatible", return_value=[0.1, 0.2, 0.3, 0.4]) as mock_embed:
        result = service.embed_text("test")
        mock_embed.assert_called_once()
        assert result == [0.1, 0.2, 0.3, 0.4]


# --- Live Ollama tests - skipped automatically if Ollama isn't running ---

pytestmark_ollama = pytest.mark.skipif(not ollama_available, reason="Ollama not running on localhost:11434")


@pytestmark_ollama
def test_ollama_embed_text_returns_real_vector():
    config = EmbeddingConfig(provider="ollama", model="nomic-embed-text", dimensions=768)
    service = EmbeddingService(config)
    vec = service.embed_text("This is a live test of the Ollama embedding path.")
    assert vec is not None
    assert len(vec) == 768
    assert all(isinstance(v, float) for v in vec)


@pytestmark_ollama
def test_ollama_embed_batch_returns_real_vectors():
    config = EmbeddingConfig(provider="ollama", model="nomic-embed-text", dimensions=768)
    service = EmbeddingService(config)
    batch = service.embed_batch(["first text", "second text", "third text"])
    assert len(batch) == 3
    assert all(v is not None and len(v) == 768 for v in batch)


@pytestmark_ollama
def test_ollama_embed_text_empty_string_returns_none():
    config = EmbeddingConfig(provider="ollama", model="nomic-embed-text", dimensions=768)
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
        embedder=EC(provider="ollama", model="nomic-embed-text", dimensions=768),
        vector_backend=backend,
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
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
