"""
Tests for core/mcp_client.py and the mcp_call action tool. A fake in-process
MCP server replaces requests.post, so no network and no LLM calls happen.
"""
import json

import pytest

from core import mcp_client
from core import action_senders
from core.employees import actions
from core.employees._db import get_connection


@pytest.fixture(autouse=True)
def mcp_env(monkeypatch):
    monkeypatch.setenv("MCP_SERVERS", "demo=https://mcp.example.com/mcp,bad.name=https://x.example.com")
    monkeypatch.setenv("MCP_ALLOWED_TOOLS", "demo.lookup,demo.search,nope.x,demo.lookup")
    monkeypatch.setenv("MCP_TOKEN_DEMO", "s3cret")
    monkeypatch.setattr(action_senders, "_is_public_https_url", lambda u: True)


class FakeResp:
    def __init__(self, status=200, headers=None, body=b"", ctype="application/json"):
        self.status_code = status
        self.headers = {"Content-Type": ctype, **(headers or {})}
        self._body = body

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def close(self):
        pass


def _json(obj):
    return json.dumps(obj).encode()


class FakeMCP:
    """Records every POST. `overrides` maps JSON-RPC method -> FakeResp or callable."""
    def __init__(self, overrides=None):
        self.calls = []
        self.overrides = overrides or {}

    def post(self, url, json=None, headers=None, timeout=None, allow_redirects=None, stream=None):
        self.calls.append({"url": url, "payload": json, "headers": dict(headers),
                           "timeout": timeout, "allow_redirects": allow_redirects})
        method = json.get("method")
        if method in self.overrides:
            o = self.overrides[method]
            return o(json) if callable(o) else o
        if method == "initialize":
            return FakeResp(headers={"Mcp-Session-Id": "sess-1"},
                            body=_json({"jsonrpc": "2.0", "id": 1,
                                        "result": {"protocolVersion": "2025-06-18"}}))
        if method == "notifications/initialized":
            return FakeResp(status=202)
        if method == "tools/call":
            return FakeResp(body=_json({"jsonrpc": "2.0", "id": 2, "result": {
                "content": [{"type": "text", "text": "found it"}]}}))
        raise AssertionError(f"unexpected method {method}")

    @property
    def methods(self):
        return [c["payload"].get("method") for c in self.calls]


@pytest.fixture
def fake(monkeypatch):
    def install(overrides=None):
        f = FakeMCP(overrides)
        monkeypatch.setattr(mcp_client.requests, "post", f.post)
        return f
    return install


# ---- config parsing ----

def test_servers_and_allowlist_parsing():
    assert mcp_client.servers() == {"demo": "https://mcp.example.com/mcp"}   # dotted name ignored
    assert mcp_client.allowed_targets() == ["demo.lookup", "demo.search"]    # unknown server dropped, deduped


def test_nothing_configured_means_no_tool(monkeypatch):
    monkeypatch.delenv("MCP_SERVERS")
    monkeypatch.delenv("MCP_ALLOWED_TOOLS")
    assert mcp_client.allowed_targets() == []
    assert "mcp_call" not in actions.available_tools()


def test_configured_tool_listed_with_targets():
    desc = actions.available_tools()["mcp_call"]
    assert "demo.lookup" in desc and "demo.search" in desc and "nope" not in desc


# ---- call_tool: happy path and headers ----

def test_happy_path_sequence_and_headers(fake):
    f = fake()
    out = mcp_client.call_tool("demo.lookup", '{"q": "invoice 7"}')
    assert out == "MCP demo.lookup: ok\nfound it"
    assert f.methods == ["initialize", "notifications/initialized", "tools/call"]
    call = f.calls[2]
    assert call["payload"]["params"] == {"name": "lookup", "arguments": {"q": "invoice 7"}}
    assert call["headers"]["Authorization"] == "Bearer s3cret"
    assert call["headers"]["Mcp-Session-Id"] == "sess-1"
    assert call["headers"]["MCP-Protocol-Version"] == "2025-06-18"
    assert "Mcp-Session-Id" not in f.calls[0]["headers"]
    assert all(c["allow_redirects"] is False and c["timeout"] == mcp_client.HTTP_TIMEOUT for c in f.calls)
    assert all(c["url"] == "https://mcp.example.com/mcp" for c in f.calls)


def test_no_token_means_no_auth_header(fake, monkeypatch):
    monkeypatch.delenv("MCP_TOKEN_DEMO")
    f = fake()
    mcp_client.call_tool("demo.lookup", "{}")
    assert "Authorization" not in f.calls[0]["headers"]


def test_empty_content_sends_empty_arguments(fake):
    f = fake()
    mcp_client.call_tool("demo.search", "")
    assert f.calls[2]["payload"]["params"]["arguments"] == {}


def test_event_stream_reply_is_parsed(fake):
    sse = (b'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\n'
           b'data: {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"streamed"}]}}\n\n')
    f = fake({"tools/call": FakeResp(body=sse, ctype="text/event-stream")})
    assert mcp_client.call_tool("demo.lookup", "{}") == "MCP demo.lookup: ok\nstreamed"


def test_tool_reported_error_is_flagged(fake):
    fake({"tools/call": FakeResp(body=_json({"jsonrpc": "2.0", "id": 2, "result": {
        "isError": True, "content": [{"type": "text", "text": "no such invoice"}]}}))})
    out = mcp_client.call_tool("demo.lookup", "{}")
    assert out.startswith("MCP demo.lookup: error") and "no such invoice" in out


def test_result_is_truncated(fake):
    fake({"tools/call": FakeResp(body=_json({"jsonrpc": "2.0", "id": 2, "result": {
        "content": [{"type": "text", "text": "x" * 10000}]}}))})
    assert len(mcp_client.call_tool("demo.lookup", "{}")) <= mcp_client.MAX_RESULT_CHARS


# ---- call_tool: refusals and failures (never raises) ----

def test_not_allowlisted_is_refused_without_any_http(fake):
    f = fake()
    for t in ("demo.delete_everything", "nope.x", "demo", "", "evil.lookup"):
        assert "refused" in mcp_client.call_tool(t, "{}")
    assert f.calls == []


def test_non_public_server_is_refused_without_http(fake, monkeypatch):
    monkeypatch.setattr(action_senders, "_is_public_https_url", lambda u: False)
    f = fake()
    assert "refused" in mcp_client.call_tool("demo.lookup", "{}")
    assert f.calls == []


@pytest.mark.parametrize("bad", ["[1, 2]", '"str"', "42"])
def test_arguments_must_be_json_object(fake, bad):
    f = fake()
    assert "refused" in mcp_client.call_tool("demo.lookup", bad)
    assert f.calls == []


def test_invalid_json_arguments_fail_safely(fake):
    f = fake()
    assert "failed" in mcp_client.call_tool("demo.lookup", "not json")
    assert f.calls == []


def test_http_error_server_error_and_oversize_fail_safely(fake):
    fake({"initialize": FakeResp(status=500)})
    assert "failed" in mcp_client.call_tool("demo.lookup", "{}")

    fake({"tools/call": FakeResp(body=_json({"jsonrpc": "2.0", "id": 2,
                                             "error": {"code": -32601, "message": "nope"}}))})
    assert "failed" in mcp_client.call_tool("demo.lookup", "{}")

    fake({"tools/call": FakeResp(body=b"y" * (mcp_client.MAX_RESPONSE_BYTES + 10))})
    assert "failed" in mcp_client.call_tool("demo.lookup", "{}")


def test_network_exception_never_raises(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")
    monkeypatch.setattr(mcp_client.requests, "post", boom)
    assert "failed" in mcp_client.call_tool("demo.lookup", "{}")


# ---- planner validation ----

def test_validate_plan_mcp_call():
    tools = {"mcp_call": "..."}
    ok = actions._validate_plan({"tool": "mcp_call", "target": "demo.lookup", "content": '{"q": 1}'}, tools)
    assert ok["channel"] == "mcp" and ok["target"] == "demo.lookup"
    assert actions._validate_plan({"tool": "mcp_call", "target": "demo.other", "content": "{}"}, tools) is None
    assert actions._validate_plan({"tool": "mcp_call", "target": "http://evil.example", "content": "{}"}, tools) is None
    assert actions._validate_plan({"tool": "mcp_call", "target": "demo.lookup", "content": "[1]"}, tools) is None
    assert actions._validate_plan({"tool": "mcp_call", "target": "demo.lookup", "content": "not json"}, tools) is None


# ---- autonomy gate: full mode and semi mode (+ approval reply) ----

@pytest.fixture
def gate(monkeypatch):
    import core.autonomy as au
    import core.employees.sensitivity as sens
    state = {"mode": "full", "calls": [], "pending_ids": [], "sensitive": False}
    monkeypatch.setattr(au, "get_autonomy_settings", lambda: {
        "mode": state["mode"], "channels": [], "actions": [],
        "approval_channel": "telegram", "approval_target": "+10000000000"})
    monkeypatch.setattr(mcp_client, "call_tool",
                        lambda target, content: (state["calls"].append((target, content)) or "MCP ok"))
    monkeypatch.setattr(au, "log_autonomous_action", lambda *a, **k: None)
    monkeypatch.setattr(au, "request_approval", lambda *a, **k: True)
    monkeypatch.setattr(au.employee_learning, "learn_from_owner_approval", lambda *a, **k: None)
    monkeypatch.setattr(sens, "is_sensitive_role", lambda r: state["sensitive"])
    yield state
    conn = get_connection()
    try:
        cur = conn.cursor()
        for a in state["pending_ids"]:
            cur.execute("DELETE FROM autonomy_pending WHERE action_id = %s", (a,))
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _run(gate_state, **kw):
    from core.employees.actions import run_action
    plan = {"tool": "mcp_call", "channel": "mcp", "target": "demo.lookup",
            "content": '{"q": "x"}', "subject": ""}
    res = run_action(plan, role=kw.get("role"))
    return res


def test_send_via_channel_mcp_dispatches(gate):
    from core.autonomy import _send_via_channel
    assert _send_via_channel("mcp", "demo.lookup", '{"q": 1}') == "MCP ok"
    assert gate["calls"] == [("demo.lookup", '{"q": 1}')]


def test_full_mode_executes_immediately(gate):
    res = _run(gate)
    assert res["status"] == "executed"
    assert gate["calls"] == [("demo.lookup", '{"q": "x"}')]


def test_semi_mode_pends_then_yes_dispatches_same_channel(gate):
    import core.autonomy as au
    gate["mode"] = "semi"
    res = _run(gate)
    assert res["status"] == "pending_approval"
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT action_id, channel, target, content FROM autonomy_pending "
                    "WHERE channel = 'mcp' AND target = 'demo.lookup' ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert row is not None
    action_id = row[0]
    gate["pending_ids"].append(action_id)
    assert gate["calls"] == []                       # nothing ran before approval
    assert row[1:] == ("mcp", "demo.lookup", '{"q": "x"}')
    reply = au.process_approval_response(f"YES {action_id}")
    assert "approved and executed" in reply
    assert gate["calls"] == [("demo.lookup", '{"q": "x"}')]


def test_sensitive_role_forced_to_semi(gate):
    gate["sensitive"] = True
    res = _run(gate, role="legal-helper")
    assert res["status"] == "pending_approval"
    assert gate["calls"] == []
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT action_id FROM autonomy_pending WHERE channel = 'mcp' AND target = 'demo.lookup'")
        gate["pending_ids"] += [r[0] for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()
