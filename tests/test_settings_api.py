import os
import json

import psycopg2
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from core import api, settings

H = {"x-api-key": "k-test"}


def _wipe():
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = c.cursor(); cur.execute("DELETE FROM app_settings"); c.commit(); c.close()


@pytest.fixture
def client(monkeypatch):
    _wipe(); settings.invalidate()
    monkeypatch.setattr(api, "RAGLEAP_API_KEY", "k-test")
    monkeypatch.setenv("ADDON_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(api.core_vector_dims, "ensure_all", lambda dims: [{"table": "stub", "status": "ok", "dims": dims}])
    yield TestClient(api.app)
    _wipe(); settings.invalidate()


def test_routes_need_the_key(client):
    for method, path in (("get", "/settings"), ("put", "/settings"), ("post", "/settings/test/llm"),
                         ("post", "/settings/test/embedding")):
        assert getattr(client, method)(path).status_code == 401, path
    assert client.get("/settings", headers=H).status_code == 200


def test_get_lists_sources_and_never_secrets(client):
    r = client.put("/settings", headers=H, json={"values": {"OPENAI_API_KEY": "sk-secret-123", "OLLAMA_MODEL": "m1"}})
    assert r.status_code == 200 and r.json()["updated"] == ["OLLAMA_MODEL", "OPENAI_API_KEY"]
    got = client.get("/settings", headers=H)
    assert "sk-secret-123" not in got.text
    d = {x["name"]: x for x in got.json()["settings"]}
    assert d["OPENAI_API_KEY"]["is_set"] and "value" not in d["OPENAI_API_KEY"]
    assert d["OLLAMA_MODEL"]["value"] == "m1" and d["OLLAMA_MODEL"]["source"] == "dashboard"
    assert got.json()["encryption_ready"] is True and "ollama" in got.json()["providers"]["llm"]


def test_invalid_input_is_rejected_atomically_without_exception_text(client):
    for body in ({"OLLAMA_MODEL": "ok", "NOPE": "x"}, {"LLM_PROVIDER": "nope"}, {"EMBEDDING_DIMENSIONS": "abc"},
                 {"OLLAMA_BASE_URL": "http://user:pw@host/v1"}, {}):
        r = client.put("/settings", headers=H, json={"values": body})
        assert r.status_code == 400, body
        assert "Traceback" not in r.text and "ValueError" not in r.text
    d = {x["name"]: x for x in client.get("/settings", headers=H).json()["settings"]}
    assert d["OLLAMA_MODEL"]["source"] != "dashboard"


def test_secret_without_encryption_key_is_refused(client, monkeypatch):
    monkeypatch.delenv("ADDON_ENCRYPTION_KEY")
    r = client.put("/settings", headers=H, json={"values": {"OPENAI_API_KEY": "sk-x"}})
    assert r.status_code == 400 and "ADDON_ENCRYPTION_KEY" in r.text


def test_blank_removes_the_dashboard_value(client):
    client.put("/settings", headers=H, json={"values": {"OLLAMA_MODEL": "m1"}})
    client.put("/settings", headers=H, json={"values": {"OLLAMA_MODEL": ""}})
    d = {x["name"]: x for x in client.get("/settings", headers=H).json()["settings"]}
    assert d["OLLAMA_MODEL"]["source"] != "dashboard"


def test_embedding_size_check_runs_only_for_embedding_provider_or_size(client):
    r = client.put("/settings", headers=H, json={"values": {"OLLAMA_MODEL": "m"}})
    assert r.json()["vector_status"] is None
    r = client.put("/settings", headers=H, json={"values": {"EMBEDDING_DIMENSIONS": 768}})
    assert r.json()["vector_status"] == [{"table": "stub", "status": "ok", "dims": 768}]


def test_url_with_credentials_rejected_directly():
    with pytest.raises(ValueError):
        settings.set_many({"OLLAMA_BASE_URL": "https://user:pw@host/v1"})


def test_llm_connection_test_outcomes(client, monkeypatch):
    from core import generation

    class Ok:
        primary_config = {"provider": "fake", "model": "m"}
        def _call_provider(self, cfg, prompt, t, n): return ("OK", None)

    class Broken(Ok):
        def _call_provider(self, cfg, prompt, t, n): raise RuntimeError("secret-detail-xyz")

    def unconfigured(): raise ValueError("secret-detail-xyz")

    monkeypatch.setattr(generation, "GenerationService", Ok)
    assert client.post("/settings/test/llm", headers=H).json() == {"ok": True, "provider": "fake", "model": "m"}
    monkeypatch.setattr(generation, "GenerationService", Broken)
    r = client.post("/settings/test/llm", headers=H)
    assert r.json()["error"] == "request_failed" and "secret-detail-xyz" not in r.text
    monkeypatch.setattr(generation, "GenerationService", unconfigured)
    r = client.post("/settings/test/llm", headers=H)
    assert r.json()["error"] == "not_configured" and "secret-detail-xyz" not in r.text


def test_embedding_connection_test_outcomes(client, monkeypatch):
    from core import embedding
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "4")

    def make(vec):
        class S:
            provider, model = "fake", "m"
            def embed_text(self, t): return vec
        return S

    monkeypatch.setattr(embedding, "EmbeddingService", make([0.0] * 4))
    assert client.post("/settings/test/embedding", headers=H).json()["dimensions"] == 4
    monkeypatch.setattr(embedding, "EmbeddingService", make([0.0] * 5))
    assert client.post("/settings/test/embedding", headers=H).json()["error"] == "size_mismatch"
    monkeypatch.setattr(embedding, "EmbeddingService", make(None))
    assert client.post("/settings/test/embedding", headers=H).json()["error"] == "request_failed"
