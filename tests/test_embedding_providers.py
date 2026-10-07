import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import core.embedding as emb


class _Fake:
    def __init__(self, dims=4, statuses=None, reverse=False, bad_dims=None):
        self.dims, self.statuses, self.reverse, self.bad_dims = dims, list(statuses or []), reverse, bad_dims
        self.requests = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                status = fake.statuses.pop(0) if fake.statuses else 200
                if status != 200:
                    self.send_response(status); self.send_header("Content-Type", "application/json"); self.end_headers()
                    self.wfile.write(b'{"error":"x"}'); return
                n = fake.bad_dims or fake.dims
                data = [{"index": i, "embedding": [float(i)] * n} for i in range(len(body["input"]))]
                if fake.reverse:
                    data.reverse()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps({"data": data}).encode())

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/v1" % self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def fake_factory(monkeypatch):
    made = []

    def make(**kw):
        f = _Fake(**kw); made.append(f); return f
    monkeypatch.setattr(emb, "EMBEDDING_RETRY_BASE_DELAY", 0)
    yield make
    for f in made:
        f.server.shutdown(); f.server.server_close()


def test_ollama_defaults_no_auth(fake_factory, monkeypatch):
    f = fake_factory(dims=768)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", f.url)
    v = emb.EmbeddingService().embed_text("hello")
    assert len(v) == 768
    r = f.requests[0]
    assert r["path"] == "/v1/embeddings" and r["body"]["model"] == "nomic-embed-text"
    assert "Authorization" not in r["headers"]


def test_openai_sends_bearer(fake_factory, monkeypatch):
    f = fake_factory(dims=1536)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", f.url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert len(emb.EmbeddingService().embed_text("hi")) == 1536
    assert f.requests[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert f.requests[0]["body"]["model"] == "text-embedding-3-small"


def _ollama(monkeypatch, f, dims="4"):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", f.url)
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", dims)


def test_batching_and_order(fake_factory, monkeypatch):
    f = fake_factory(dims=4, reverse=True)
    _ollama(monkeypatch, f)
    monkeypatch.setattr(emb, "EMBEDDING_BATCH_SIZE", 2)
    out = emb.EmbeddingService().embed_batch(["a", "b", "c", "d", "e"])
    assert len(f.requests) == 3
    assert [v[0] for v in out] == [0.0, 1.0, 0.0, 1.0, 0.0]


def test_retry_on_429_then_success(fake_factory, monkeypatch):
    f = fake_factory(dims=4, statuses=[429, 429])
    _ollama(monkeypatch, f)
    assert emb.EmbeddingService().embed_text("x") is not None
    assert len(f.requests) == 3


def test_wrong_size_returns_none(fake_factory, monkeypatch):
    f = fake_factory(dims=4, bad_dims=5)
    _ollama(monkeypatch, f)
    assert emb.EmbeddingService().embed_batch(["a", "b"]) == [None, None]


def test_http_500_returns_none_without_retry(fake_factory, monkeypatch):
    f = fake_factory(dims=4, statuses=[500])
    _ollama(monkeypatch, f)
    assert emb.EmbeddingService().embed_text("x") is None
    assert len(f.requests) == 1


def test_config_errors(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    with pytest.raises(ValueError):
        emb.EmbeddingService()                       # no key
    monkeypatch.setenv("EMBEDDING_PROVIDER", "together")
    monkeypatch.setenv("TOGETHER_API_KEY", "k")
    with pytest.raises(ValueError):
        emb.EmbeddingService()                       # no model
    monkeypatch.setenv("TOGETHER_EMBEDDING_MODEL", "m")
    with pytest.raises(ValueError):
        emb.EmbeddingService()                       # no dimensions
    monkeypatch.setenv("EMBEDDING_PROVIDER", "custom")
    with pytest.raises(ValueError):
        emb.EmbeddingService()                       # no base url
    monkeypatch.setenv("EMBEDDING_PROVIDER", "nope")
    with pytest.raises(ValueError):
        emb.EmbeddingService()


def test_configured_dimensions(monkeypatch):
    assert emb.configured_dimensions() == 3072
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    assert emb.configured_dimensions() == 768
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    assert emb.configured_dimensions() == 1536
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "512")
    assert emb.configured_dimensions() == 512
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "abc")
    assert emb.configured_dimensions() == 1536


def test_empty_text_none(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert emb.EmbeddingService().embed_text("   ") is None
    assert emb.EmbeddingService().embed_batch([]) == []


def test_gemini_path_unchanged(monkeypatch):
    class _Vals:
        def __init__(self, v): self.values = v

    class _Models:
        def embed_content(self, model, contents):
            items = contents if isinstance(contents, list) else [contents]
            return types.SimpleNamespace(embeddings=[_Vals([1.0, 2.0]) for _ in items])

    class _Client:
        def __init__(self, api_key): self.models = _Models()

    genai = types.ModuleType("google.genai"); genai.Client = _Client
    google = types.ModuleType("google"); google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    s = emb.EmbeddingService()
    assert s.provider == "gemini" and s.dimensions == 3072
    assert s.embed_text("a") == [1.0, 2.0]
    assert s.embed_batch(["a", "b"]) == [[1.0, 2.0], [1.0, 2.0]]
