"""
Tests for the opt-in RAGLEAP_API_KEY middleware in core/api.py.

RAGLEAP_API_KEY is read once, at module import time, into core.api.RAGLEAP_API_KEY --
so tests that need "key is set" behavior monkeypatch that module attribute directly
rather than os.environ (which core.api already finished reading by the time any test
runs), matching how this project already tests module-level config elsewhere.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import api as api_module
from core.api import app


@pytest.fixture
def client():
    return TestClient(app)


def _set_key(monkeypatch, value):
    monkeypatch.setattr(api_module, "RAGLEAP_API_KEY", value)


def test_health_exempt_when_key_unset(client, monkeypatch):
    _set_key(monkeypatch, "")
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_exempt_even_when_key_set(client, monkeypatch):
    _set_key(monkeypatch, "s3cret")
    r = client.get("/health")
    assert r.status_code == 200


def _mocked_employees_call(client, headers=None):
    with patch.object(api_module.employee_roles, "seed_default_roles"), \
         patch.object(api_module.employee_memory, "seed_default_memory_seeds"), \
         patch.object(api_module.employee_roles, "list_roles", return_value=[{"role": "support"}]):
        return client.get("/employees", headers=headers or {})


def test_protected_route_open_when_key_unset(client, monkeypatch):
    _set_key(monkeypatch, "")
    r = _mocked_employees_call(client)
    assert r.status_code == 200
    assert r.json() == {"roles": [{"role": "support"}]}


def test_protected_route_rejects_missing_header_when_key_set(client, monkeypatch):
    _set_key(monkeypatch, "s3cret")
    r = _mocked_employees_call(client)
    assert r.status_code == 401
    assert "detail" in r.json()


def test_protected_route_rejects_wrong_key(client, monkeypatch):
    _set_key(monkeypatch, "s3cret")
    r = _mocked_employees_call(client, {"x-api-key": "wrong"})
    assert r.status_code == 401


def test_protected_route_accepts_correct_key(client, monkeypatch):
    _set_key(monkeypatch, "s3cret")
    r = _mocked_employees_call(client, {"x-api-key": "s3cret"})
    assert r.status_code == 200
    assert r.json() == {"roles": [{"role": "support"}]}


def test_key_comparison_is_exact_not_prefix_or_substring(client, monkeypatch):
    _set_key(monkeypatch, "s3cret")
    r = _mocked_employees_call(client, {"x-api-key": "s3cretextra"})
    assert r.status_code == 401
    r2 = _mocked_employees_call(client, {"x-api-key": "s3cre"})
    assert r2.status_code == 401


def test_webhook_paths_exempt_from_key_even_when_set():
    """The middleware itself must not block /webhook/* when a key is configured --
    those routes verify platform signatures independently and must remain reachable
    by external platforms with no X-API-Key header at all."""
    assert api_module.API_KEY_EXEMPT_PREFIXES == ("/webhook/",)
    for path in ("/webhook/whatsapp", "/webhook/telegram", "/webhook/discord"):
        assert path.startswith(api_module.API_KEY_EXEMPT_PREFIXES)


@pytest.mark.asyncio
async def test_middleware_function_directly_open_when_unset(monkeypatch):
    _set_key(monkeypatch, "")
    called = {}
    async def call_next(req):
        called["hit"] = True
        return "response"
    class FakeURL:
        path = "/some/protected/route"
    class FakeRequest:
        url = FakeURL()
        headers = {}
    result = await api_module.require_api_key(FakeRequest(), call_next)
    assert result == "response"
    assert called.get("hit") is True


@pytest.mark.asyncio
async def test_middleware_function_directly_blocks_when_set_and_missing(monkeypatch):
    _set_key(monkeypatch, "s3cret")
    called = {}
    async def call_next(req):
        called["hit"] = True
        return "response"
    class FakeURL:
        path = "/some/protected/route"
    class FakeRequest:
        url = FakeURL()
        headers = {}
    result = await api_module.require_api_key(FakeRequest(), call_next)
    assert result.status_code == 401
    assert "hit" not in called
