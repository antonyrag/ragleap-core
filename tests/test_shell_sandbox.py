"""
Tests for the shell mode of the sandbox: client (core/code_exec.run_shell),
runner shell spec/HTTP validation, the run_shell tool, and the gate paths.
No Docker, network or LLM is used.
"""
import importlib.util
import pathlib
import threading

import pytest
import requests as real_requests

from core import code_exec
from core.employees import actions
from core.employees._db import get_connection

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sandbox_runner_shell", ROOT / "sandbox" / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {"exit_code": 0, "stdout": "3\n", "stderr": ""}

    def json(self):
        return self._body


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("SHELL_EXEC_ENABLED", "true")
    monkeypatch.setenv("SANDBOX_TOKEN", "tok123")
    monkeypatch.delenv("CODE_EXEC_ENABLED", raising=False)
    monkeypatch.delenv("SANDBOX_URL", raising=False)


def stub_post(monkeypatch, resp=None, exc=None):
    calls = []

    def fake(url, json=None, headers=None, timeout=None, allow_redirects=None):
        calls.append({"url": url, "json": json, "headers": headers, "allow_redirects": allow_redirects})
        if exc:
            raise exc
        return resp or FakeResp()
    monkeypatch.setattr(code_exec.requests, "post", fake)
    return calls


# ---- client ----

def test_flags_are_independent(monkeypatch):
    monkeypatch.setenv("SANDBOX_TOKEN", "t")
    monkeypatch.setenv("SHELL_EXEC_ENABLED", "true")
    monkeypatch.delenv("CODE_EXEC_ENABLED", raising=False)
    assert code_exec.shell_enabled() and not code_exec.enabled()
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    monkeypatch.delenv("SHELL_EXEC_ENABLED")
    assert code_exec.enabled() and not code_exec.shell_enabled()
    monkeypatch.setenv("SHELL_EXEC_ENABLED", "true")
    monkeypatch.delenv("SANDBOX_TOKEN")
    assert not code_exec.shell_enabled()


def test_run_shell_request_shape(on, monkeypatch):
    calls = stub_post(monkeypatch)
    assert code_exec.run_shell("echo 3") == "Shell run: exit 0\nstdout:\n3\n"
    c = calls[0]
    assert c["url"] == "http://sandbox:8099/run" and c["json"] == {"shell": "echo 3"}
    assert c["headers"] == {"Authorization": "Bearer tok123"} and c["allow_redirects"] is False


def test_run_shell_refusals_make_no_http_call(on, monkeypatch):
    calls = stub_post(monkeypatch)
    assert "refused" in code_exec.run_shell("  ")
    assert "refused" in code_exec.run_shell("x" * (code_exec.MAX_CODE_CHARS + 1))
    assert "refused" in code_exec.run_shell("echo\x00hi")
    monkeypatch.delenv("SHELL_EXEC_ENABLED")
    assert "refused" in code_exec.run_shell("echo hi")
    assert calls == []


def test_run_shell_errors_never_raise(on, monkeypatch):
    stub_post(monkeypatch, FakeResp(body={"exit_code": 137, "timed_out": True}))
    assert "timed out" in code_exec.run_shell("sleep 99")
    stub_post(monkeypatch, FakeResp(status=429))
    assert "busy" in code_exec.run_shell("ls")
    stub_post(monkeypatch, exc=ConnectionError("down"))
    assert "failed" in code_exec.run_shell("ls")


def test_existing_run_code_labels_unchanged(monkeypatch):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    monkeypatch.setenv("SANDBOX_TOKEN", "t")
    stub_post(monkeypatch)
    assert code_exec.run_code("print(3)").startswith("Code run: exit 0")


# ---- planner ----

def test_run_shell_listed_only_when_shell_enabled(monkeypatch):
    for k in ("CODE_EXEC_ENABLED", "SHELL_EXEC_ENABLED", "SANDBOX_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    t = actions.available_tools()
    assert "run_shell" not in t and "run_code" not in t
    monkeypatch.setenv("SANDBOX_TOKEN", "t")
    monkeypatch.setenv("SHELL_EXEC_ENABLED", "true")
    t = actions.available_tools()
    assert "run_shell" in t and "run_code" not in t        # independent of Python mode


def test_validate_plan_run_shell():
    tools = {"run_shell": "..."}
    ok = actions._validate_plan({"tool": "run_shell", "target": "http://evil", "content": "ls | wc -l"}, tools)
    assert ok["channel"] == "shell" and ok["target"] == "" and ok["content"] == "ls | wc -l"
    assert actions._validate_plan({"tool": "run_shell", "target": "", "content": "echo hi; " * 400}, tools) is None
    assert actions._validate_plan({"tool": "run_shell", "target": "", "content": " "}, tools) is None


# ---- runner: spec + HTTP ----

def test_shell_spec_same_lockdown_command_only_in_env():
    py = runner.build_spec("print(1)")
    sh = runner.build_spec("echo hi; $(reboot) '; rm -rf /", "shell")
    assert sh["Env"] == ["CMD=echo hi; $(reboot) '; rm -rf /"]
    assert sh["Cmd"][:2] == ["sh", "-c"] and "reboot" not in " ".join(sh["Cmd"])
    for k in ("Image", "User", "WorkingDir", "NetworkDisabled", "Labels", "HostConfig"):
        assert sh[k] == py[k], k


def test_default_mode_is_still_python():
    s = runner.build_spec("print(1)")
    assert s["Cmd"][0] == "python" and s["Env"] == ["CODE=print(1)"]


@pytest.fixture
def server(monkeypatch):
    seen = []
    monkeypatch.setattr(runner, "TOKEN", "tok")
    monkeypatch.setattr(runner, "run_in_sandbox",
                        lambda code, mode="python": (seen.append((mode, code)) or
                                                     {"exit_code": 0, "stdout": "", "stderr": ""}))
    srv = runner.ThreadingHTTPServer(("127.0.0.1", 0), runner.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", seen
    srv.shutdown()
    srv.server_close()


def test_http_routes_shell_and_code_to_right_mode(server):
    url, seen = server
    h = {"Authorization": "Bearer tok"}
    assert real_requests.post(url + "/run", json={"shell": "ls"}, headers=h).status_code == 200
    assert real_requests.post(url + "/run", json={"code": "print(1)"}, headers=h).status_code == 200
    assert seen == [("shell", "ls"), ("python", "print(1)")]


def test_http_rejects_ambiguous_or_bad_bodies(server):
    url, seen = server
    h = {"Authorization": "Bearer tok"}
    for body in ({"shell": "ls", "code": "print(1)"}, {}, {"shell": ""}, {"shell": 5},
                 {"shell": "a" * (runner.MAX_CODE_CHARS + 1)}, {"shell": "a\u0000b"}):
        assert real_requests.post(url + "/run", json=body, headers=h).status_code in (400, 413)
    assert real_requests.post(url + "/run", json={"shell": "ls"}).status_code == 401
    assert seen == []


# ---- gate ----

@pytest.fixture
def gate(monkeypatch):
    import core.autonomy as au
    import core.employees.sensitivity as sens
    state = {"mode": "full", "ran": [], "sensitive": False}
    monkeypatch.setattr(au, "get_autonomy_settings", lambda: {
        "mode": state["mode"], "channels": [], "actions": [],
        "approval_channel": "telegram", "approval_target": "+10000000000"})
    monkeypatch.setattr(code_exec, "run_shell", lambda c: (state["ran"].append(c) or "Shell run: exit 0"))
    monkeypatch.setattr(au, "log_autonomous_action", lambda *a, **k: None)
    monkeypatch.setattr(au, "request_approval", lambda *a, **k: True)
    monkeypatch.setattr(au.employee_learning, "learn_from_owner_approval", lambda *a, **k: None)
    monkeypatch.setattr(sens, "is_sensitive_role", lambda r: state["sensitive"])
    yield state
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM autonomy_pending WHERE channel = 'shell'")
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _plan(role=None):
    from core.employees.actions import run_action
    return run_action({"tool": "run_shell", "channel": "shell", "target": "",
                       "content": "ls /tmp", "subject": ""}, role=role)


def test_send_via_channel_shell_dispatches(gate):
    from core.autonomy import _send_via_channel
    assert _send_via_channel("shell", "", "uname") == "Shell run: exit 0"
    assert gate["ran"] == ["uname"]


def test_full_mode_runs_immediately(gate):
    assert _plan()["status"] == "executed" and gate["ran"] == ["ls /tmp"]


def test_semi_mode_pends_then_yes_runs(gate):
    import core.autonomy as au
    gate["mode"] = "semi"
    assert _plan()["status"] == "pending_approval" and gate["ran"] == []
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT action_id, content FROM autonomy_pending WHERE channel = 'shell' "
                    "ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert row is not None and row[1] == "ls /tmp"
    assert "approved and executed" in au.process_approval_response(f"YES {row[0]}")
    assert gate["ran"] == ["ls /tmp"]


def test_sensitive_role_forced_to_semi(gate):
    gate["sensitive"] = True
    assert _plan(role="legal-helper")["status"] == "pending_approval" and gate["ran"] == []
