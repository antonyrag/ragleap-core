import json
import os

import psycopg2
import pytest
from cryptography.fernet import Fernet

from core import settings, embedding as emb, generation


def _wipe():
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = c.cursor()
    cur.execute("DELETE FROM app_settings")
    c.commit()
    c.close()


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    _wipe(); settings.invalidate()
    monkeypatch.setenv("ADDON_ENCRYPTION_KEY", Fernet.generate_key().decode())
    yield
    _wipe(); settings.invalidate()


def test_env_then_default(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "m1")
    assert settings.get("OLLAMA_MODEL") == "m1" and settings.source("OLLAMA_MODEL") == "env"
    monkeypatch.delenv("OLLAMA_MODEL")
    assert settings.get("OLLAMA_MODEL", "x") == "x" and settings.source("OLLAMA_MODEL") == "default"


def test_dashboard_wins_then_reverts(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "m1")
    settings.set_many({"OLLAMA_MODEL": "m2"})
    assert settings.get("OLLAMA_MODEL") == "m2" and settings.source("OLLAMA_MODEL") == "dashboard"
    settings.set_many({"OLLAMA_MODEL": None})
    assert settings.get("OLLAMA_MODEL") == "m1" and settings.source("OLLAMA_MODEL") == "env"


def test_secret_encrypted_and_write_only(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings.set_many({"OPENAI_API_KEY": "sk-abc123"})
    assert settings.get("OPENAI_API_KEY") == "sk-abc123"
    c = psycopg2.connect(os.environ["DATABASE_URL"]); cur = c.cursor()
    cur.execute("SELECT value, is_secret FROM app_settings WHERE key = 'OPENAI_API_KEY'")
    stored, is_secret = cur.fetchone(); c.close()
    assert is_secret and stored != "sk-abc123" and stored.startswith("gAAAA")
    d = {x["name"]: x for x in settings.describe()}
    assert d["OPENAI_API_KEY"]["is_set"] and "value" not in d["OPENAI_API_KEY"]
    assert "sk-abc123" not in json.dumps(settings.describe())


def test_secret_needs_encryption_key(monkeypatch):
    monkeypatch.delenv("ADDON_ENCRYPTION_KEY")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        settings.set_many({"OPENAI_API_KEY": "sk-x"})
    assert settings.get("OPENAI_API_KEY") == ""


def test_wrong_decrypt_key_falls_back(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings.set_many({"OPENAI_API_KEY": "sk-abc"})
    monkeypatch.setenv("ADDON_ENCRYPTION_KEY", Fernet.generate_key().decode())
    settings.invalidate()
    assert settings.get("OPENAI_API_KEY") == ""


def test_validation_rules():
    for bad in ({"NOPE": "x"}, {"EMBEDDING_DIMENSIONS": "abc"}, {"EMBEDDING_DIMENSIONS": "0"},
                {"EMBEDDING_DIMENSIONS": "99999"}, {"LLM_PROVIDER": "nope"},
                {"OLLAMA_BASE_URL": "ftp://x"}, {"OLLAMA_MODEL": "a\nb"}, {"OLLAMA_MODEL": "x" * 600},
                {"LLM_FALLBACK_PROVIDERS": "groq,nope"}):
        with pytest.raises(ValueError):
            settings.set_many(bad)
    settings.set_many({"EMBEDDING_DIMENSIONS": 768, "LLM_PROVIDER": "OLLAMA",
                       "OLLAMA_BASE_URL": "http://host.docker.internal:11434/v1",
                       "LLM_FALLBACK_PROVIDERS": "groq, gemini"})
    assert settings.get("EMBEDDING_DIMENSIONS") == "768" and settings.get("LLM_PROVIDER") == "ollama"
    assert settings.get("LLM_FALLBACK_PROVIDERS") == "groq,gemini"


def test_batch_is_atomic():
    with pytest.raises(ValueError):
        settings.set_many({"OLLAMA_MODEL": "a", "NOPE": "b"})
    assert "OLLAMA_MODEL" not in {k for k, _ in [(r["name"], 0) for r in settings.describe() if r["source"] == "dashboard"]}


def test_database_down_falls_back_to_env(monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(settings, "get_connection", boom)
    settings.invalidate()
    monkeypatch.setenv("OLLAMA_MODEL", "from-env")
    assert settings.get("OLLAMA_MODEL") == "from-env"


def test_embedding_and_generation_read_dashboard_values(monkeypatch):
    monkeypatch.delenv("EMBEDDING_DIMENSIONS", raising=False)
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    settings.set_many({"EMBEDDING_DIMENSIONS": "768"})
    assert emb.configured_dimensions() == 768
    settings.set_many({"GROQ_API_KEY": "gk", "GROQ_MODEL": "gm"})
    cfg = generation._resolve_provider_config("groq")
    assert cfg["model"] == "gm" and cfg["api_key"] == "gk"


def test_describe_flags():
    d = {x["name"]: x for x in settings.describe()}
    assert d["OPENAI_API_KEY"]["secret"] is True and d["OLLAMA_MODEL"]["secret"] is False
    assert "LLM_PROVIDER" in d and "GEMINI_API_KEY" in d
