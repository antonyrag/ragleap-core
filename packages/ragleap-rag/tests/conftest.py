import os
import pytest

os.environ.setdefault("GEMINI_API_KEY", "fake-test-key")

from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap.embedding import EmbeddingService
from ragleap.generation import GenerationService

TEST_DATABASE_URL = os.environ.get(
    "RAGLEAP_TEST_DATABASE_URL",
    "postgresql://ragleap_test_user:ragleap_test_pass@127.0.0.1:5432/ragleap_test",
)
TEST_DIMENSIONS = 8  # small & fast — real value (3072) is needless for plumbing tests


def _fake_vector(text: str, dimensions: int = TEST_DIMENSIONS):
    """Deterministic pseudo-embedding: same text always -> same vector,
    different text -> (virtually certainly) a different vector. Enough
    to exercise real similarity search without a real embedding model."""
    import hashlib
    h = hashlib.sha256(text.encode()).digest()
    return [(h[i % len(h)] / 255.0) for i in range(dimensions)]


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    """No network, no real API key needed, fully reproducible."""
    def fake_embed_text(self, text):
        if not text or not text.strip():
            return None
        return _fake_vector(text, self.dimensions)

    def fake_embed_batch(self, texts):
        return [fake_embed_text(self, t) for t in texts]

    monkeypatch.setattr(EmbeddingService, "embed_text", fake_embed_text)
    monkeypatch.setattr(EmbeddingService, "embed_batch", fake_embed_batch)


@pytest.fixture(autouse=True)
def fake_generator(monkeypatch):
    """No network. Canned but realistic-shaped responses so tests can
    assert on the actual RagLeap response contract."""
    def fake_call_provider(self, config, prompt, temperature, max_tokens, response_format=None):
        if response_format is not None:
            import json
            # Fake providers don't call a real model, so return something
            # type-conformant to whatever top-level type the schema
            # declares (defaults to object) - enough for structured-mode
            # tests that check shape/plumbing, not real model behavior.
            expected_type = response_format.get("type", "object")
            fake_payload = {"result": "fake"} if expected_type == "object" else (["fake"] if expected_type == "array" else "fake")
            return (
                json.dumps(fake_payload),
                {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "native",
            )
        return (
            f"[fake answer based on context] {prompt[-120:]}",
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            None,
        )

    def fake_stream_provider(self, config, prompt, temperature, max_tokens):
        for word in ["This ", "is ", "a ", "fake ", "streamed ", "answer."]:
            yield word

    monkeypatch.setattr(GenerationService, "_call_provider", fake_call_provider)
    monkeypatch.setattr(GenerationService, "_stream_provider", fake_stream_provider)


@pytest.fixture(scope="session")
def database_url():
    return TEST_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def _init_schema_once(database_url):
    """Schema init is idempotent (IF NOT EXISTS everywhere), so doing
    this once per test session is safe and matches real-world usage."""
    rag = RagLeap(
        database_url=database_url,
        embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
    )
    rag.init_schema()
    yield


@pytest.fixture(autouse=True)
def _clean_tables(database_url):
    """Truncate data tables before each test so tests are isolated
    from each other. Schema/extensions/indexes stay in place."""
    import psycopg2
    conn = psycopg2.connect(database_url)
    try:
        cur = conn.cursor()
        cur.execute("TRUNCATE conversation_messages, conversations, chunks, documents CASCADE;")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    yield


@pytest.fixture
def rag(database_url):
    """A fresh RagLeap instance per test. Fake providers are wired in
    automatically via the autouse fixtures above."""
    return RagLeap(
        database_url=database_url,
        embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
    )
