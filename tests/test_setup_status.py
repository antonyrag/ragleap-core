import json
import os
import socket

import psycopg2
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from core import api, autonomy, generation, settings, setup_status, vector_dims

CLEAR = ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET", "MCP_SERVERS", "SANDBOX_URL")


def set_autonomy(monkeypatch, **kw):
    base = {"mode": "off", "channels": [], "actions": [], "approval_channel": "telegram", "approval_target": ""}
    base.update(kw)
    monkeypatch.setattr(autonomy, "get_autonomy_settings", lambda: dict(base))


def by(data):
    return {i["id"]: i for i in data["items"]}


@pytest.fixture
def clean(monkeypatch):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = c.cursor(); cur.execute("DELETE FROM app_settings"); c.commit(); c.close()
    settings.invalidate()
    for name in CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ADDON_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(generation, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(generation, "LLM_FALLBACK_PROVIDERS", [])
    monkeypatch.setattr(vector_dims, "status", lambda dims: [])
    set_autonomy(monkeypatch)
    yield
    settings.invalidate()


def test_route_needs_the_key(clean, monkeypatch):
    monkeypatch.setattr(api, "RAGLEAP_API_KEY", "k-test")
    c = TestClient(api.app)
    assert c.get("/setup/status").status_code == 401
    r = c.get("/setup/status", headers={"x-api-key": "k-test"})
    assert r.status_code == 200 and r.json()["items"] and by(r.json())["api_key"]["state"] == "ok"


def test_nothing_configured_is_not_ready_and_every_open_item_says_what_to_do(clean):
    d = setup_status.build(api_key_set=False)
    it = by(d)
    assert d["ready"] is False and "3 required steps left" in d["summary"]
    for name in ("api_key", "chat_ai", "embeddings"):
        assert it[name]["state"] == "todo" and it[name]["required"] and it[name]["action"]
    assert it["chat_ai"]["fix"] == "settings" and it["embeddings"]["fix"] == "settings"
    for i in d["items"]:
        if i["state"] in ("todo", "warn"):
            assert i["action"], i["id"]


def test_configured_is_ready(clean, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-sentinel-A")
    d = setup_status.build(api_key_set=True)
    it = by(d)
    assert d["ready"] is True and d["summary"] == "Everything required is set up."
    assert it["chat_ai"]["state"] == "ok" and "gemini" in it["chat_ai"]["detail"]
    assert it["embeddings"]["state"] == "ok" and "3072" in it["embeddings"]["detail"]


def test_dashboard_settings_count_as_configured(clean):
    settings.set_many({"GEMINI_API_KEY": "sk-sentinel-A"})
    assert by(setup_status.build(api_key_set=True))["chat_ai"]["state"] == "ok"


def test_no_secret_or_target_ever_appears(clean, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-sentinel-AAA")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-sentinel-BBB")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "whs-sentinel-DDD")
    monkeypatch.setenv("SANDBOX_TOKEN", "sbx-sentinel-CCC")
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    monkeypatch.setattr(setup_status, "_reachable", lambda url, timeout=1.0: True)
    set_autonomy(monkeypatch, mode="semi", approval_target="chat-sentinel-EEE")
    text = json.dumps(setup_status.build(api_key_set=True))
    for s in ("sentinel-AAA", "sentinel-BBB", "sentinel-CCC", "sentinel-DDD", "sentinel-EEE"):
        assert s not in text, s


def test_vector_mismatch_blocks_ready_and_resizable_does_not(clean, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(vector_dims, "status", lambda dims: [
        {"table": "chunks", "status": "mismatch", "have": 3072, "want": 768, "rows": 5}])
    d = setup_status.build(api_key_set=True)
    e = by(d)["embeddings"]
    assert d["ready"] is False and e["state"] == "todo" and "chunks" in e["detail"] and "3072" in e["detail"]
    monkeypatch.setattr(vector_dims, "status", lambda dims: [
        {"table": "chunks", "status": "will_resize", "have": 3072, "want": 768, "rows": 0}])
    d = setup_status.build(api_key_set=True)
    assert d["ready"] is True and "resized" in by(d)["embeddings"]["detail"]


def test_a_failing_check_never_raises_and_never_leaks_the_error(clean, monkeypatch):
    def boom():
        raise RuntimeError("secret-detail-xyz")
    monkeypatch.setattr(autonomy, "get_autonomy_settings", boom)
    d = setup_status.build(api_key_set=True)
    it = by(d)
    assert it["autonomy"]["state"] == "warn" and it["approvals"]["state"] == "warn"
    assert "secret-detail-xyz" not in json.dumps(d)


def test_autonomy_and_approval_ping_cases(clean, monkeypatch):
    it = by(setup_status.build(api_key_set=True))
    assert it["autonomy"]["state"] == "info" and it["approvals"]["state"] == "info"
    set_autonomy(monkeypatch, mode="semi")
    it = by(setup_status.build(api_key_set=True))
    assert it["autonomy"]["state"] == "ok" and it["approvals"]["state"] == "warn"
    set_autonomy(monkeypatch, mode="semi", approval_target="123")
    it = by(setup_status.build(api_key_set=True))
    assert it["approvals"]["state"] == "warn" and "TELEGRAM_BOT_TOKEN" in it["approvals"]["detail"]
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    assert by(setup_status.build(api_key_set=True))["approvals"]["state"] == "ok"
    set_autonomy(monkeypatch, mode="full")
    assert by(setup_status.build(api_key_set=True))["autonomy"]["state"] == "warn"


def test_tools_and_sandbox(clean, monkeypatch):
    it = by(setup_status.build(api_key_set=True))
    assert it["tools"]["state"] == "info" and "sandbox" not in it
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    it = by(setup_status.build(api_key_set=True))
    assert it["tools"]["state"] == "warn" and "SANDBOX_TOKEN" in it["tools"]["detail"] and "sandbox" not in it
    monkeypatch.setenv("SANDBOX_TOKEN", "t")
    monkeypatch.setattr(setup_status, "_reachable", lambda url, timeout=1.0: False)
    assert by(setup_status.build(api_key_set=True))["sandbox"]["state"] == "warn"
    monkeypatch.setattr(setup_status, "_reachable", lambda url, timeout=1.0: True)
    assert by(setup_status.build(api_key_set=True))["sandbox"]["state"] == "ok"


def test_reachable_helper():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    try:
        assert setup_status._reachable("http://127.0.0.1:%d" % srv.getsockname()[1]) is True
    finally:
        srv.close()
    assert setup_status._reachable("http://127.0.0.1:1") is False
    assert setup_status._reachable("ftp://x") is False and setup_status._reachable("not a url") is False


def test_budgets_and_throttle(clean, monkeypatch):
    assert by(setup_status.build(api_key_set=True))["budgets"]["state"] == "warn"
    monkeypatch.setenv("BUDGET_DAILY_TOKENS", "1000")
    assert by(setup_status.build(api_key_set=True))["budgets"]["state"] == "ok"
    assert by(setup_status.build(api_key_set=True))["throttle"]["state"] == "ok"
    monkeypatch.setenv("AUTH_THROTTLE", "off")
    assert by(setup_status.build(api_key_set=True))["throttle"]["state"] == "warn"


def test_telegram_item_reports_yes_no_only(clean, monkeypatch):
    d = by(setup_status.build(api_key_set=True))["telegram"]["detail"]
    assert "Bot token: not set" in d and "secret: not set" in d
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    assert "Bot token: set" in by(setup_status.build(api_key_set=True))["telegram"]["detail"]
