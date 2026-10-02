"""
Tests for the code sandbox: core/code_exec.py (client), sandbox/runner.py
(runner, with a fake Docker API), the run_code action tool, and the autonomy
gate paths. No Docker, network or LLM is used. The spec/compose tests are
deliberate tripwires: weakening the sandbox must fail CI.
"""
import importlib.util
import json
import pathlib
import threading

import pytest
import requests as real_requests

from core import code_exec
from core.employees import actions
from core.employees._db import get_connection

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sandbox_runner", ROOT / "sandbox" / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


# ---------------- client: core/code_exec.py ----------------

@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    monkeypatch.setenv("SANDBOX_TOKEN", "tok123")
    monkeypatch.delenv("SANDBOX_URL", raising=False)


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {"exit_code": 0, "stdout": "42\n", "stderr": ""}

    def json(self):
        return self._body


def stub_post(monkeypatch, resp=None, exc=None):
    calls = []

    def fake(url, json=None, headers=None, timeout=None, allow_redirects=None):
        calls.append({"url": url, "json": json, "headers": headers,
                      "timeout": timeout, "allow_redirects": allow_redirects})
        if exc:
            raise exc
        return resp or FakeResp()
    monkeypatch.setattr(code_exec.requests, "post", fake)
    return calls


def test_enabled_needs_flag_and_token(monkeypatch):
    monkeypatch.delenv("CODE_EXEC_ENABLED", raising=False)
    monkeypatch.delenv("SANDBOX_TOKEN", raising=False)
    assert code_exec.enabled() is False
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    assert code_exec.enabled() is False            # flag without token
    monkeypatch.setenv("SANDBOX_TOKEN", "t")
    assert code_exec.enabled() is True
    monkeypatch.setenv("CODE_EXEC_ENABLED", "yes")
    assert code_exec.enabled() is False            # only the literal "true"


def test_happy_path_request_shape(on, monkeypatch):
    calls = stub_post(monkeypatch)
    out = code_exec.run_code("print(6*7)")
    assert out == "Code run: exit 0\nstdout:\n42\n"
    c = calls[0]
    assert c["url"] == "http://sandbox:8099/run"
    assert c["json"] == {"code": "print(6*7)"}
    assert c["headers"] == {"Authorization": "Bearer tok123"}
    assert c["allow_redirects"] is False and c["timeout"] == code_exec.HTTP_TIMEOUT


def test_refusals_make_no_http_call(on, monkeypatch):
    calls = stub_post(monkeypatch)
    assert "refused" in code_exec.run_code("   ")
    assert "refused" in code_exec.run_code("x" * (code_exec.MAX_CODE_CHARS + 1))
    monkeypatch.delenv("CODE_EXEC_ENABLED")
    assert "refused" in code_exec.run_code("print(1)")
    assert calls == []


def test_flags_busy_errors_and_truncation(on, monkeypatch):
    stub_post(monkeypatch, FakeResp(body={"exit_code": -1, "stdout": "", "stderr": "", "timed_out": True}))
    assert "timed out" in code_exec.run_code("while True: pass")
    stub_post(monkeypatch, FakeResp(body={"exit_code": 137, "oom": True}))
    assert "out of memory" in code_exec.run_code("x=[0]*10**9")
    stub_post(monkeypatch, FakeResp(status=429))
    assert "busy" in code_exec.run_code("print(1)")
    stub_post(monkeypatch, FakeResp(status=500))
    assert "failed" in code_exec.run_code("print(1)")
    stub_post(monkeypatch, FakeResp(body={"exit_code": 0, "stdout": "y" * 10000}))
    assert len(code_exec.run_code("print(1)")) <= code_exec.MAX_RESULT_CHARS


def test_network_error_never_raises(on, monkeypatch):
    stub_post(monkeypatch, exc=ConnectionError("down"))
    assert "failed" in code_exec.run_code("print(1)")


# ---------------- planner ----------------

def test_run_code_listed_only_when_enabled(monkeypatch):
    monkeypatch.delenv("CODE_EXEC_ENABLED", raising=False)
    monkeypatch.delenv("SANDBOX_TOKEN", raising=False)
    assert "run_code" not in actions.available_tools()
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    monkeypatch.setenv("SANDBOX_TOKEN", "t")
    assert "run_code" in actions.available_tools()


def test_validate_plan_run_code():
    tools = {"run_code": "..."}
    ok = actions._validate_plan({"tool": "run_code", "target": "http://evil", "content": "print(1)"}, tools)
    assert ok["channel"] == "code" and ok["target"] == "" and ok["content"] == "print(1)"
    too_long = "x=1\n" * 1000
    assert actions._validate_plan({"tool": "run_code", "target": "", "content": too_long}, tools) is None
    assert actions._validate_plan({"tool": "run_code", "target": "", "content": "  "}, tools) is None


# ---------------- gate: full / semi (+ YES reply) / sensitive ----------------

@pytest.fixture
def gate(monkeypatch):
    import core.autonomy as au
    import core.employees.sensitivity as sens
    state = {"mode": "full", "ran": [], "pending_ids": [], "sensitive": False}
    monkeypatch.setattr(au, "get_autonomy_settings", lambda: {
        "mode": state["mode"], "channels": [], "actions": [],
        "approval_channel": "telegram", "approval_target": "+10000000000"})
    monkeypatch.setattr(code_exec, "run_code", lambda code: (state["ran"].append(code) or "Code run: exit 0"))
    monkeypatch.setattr(au, "log_autonomous_action", lambda *a, **k: None)
    monkeypatch.setattr(au, "request_approval", lambda *a, **k: True)
    monkeypatch.setattr(au.employee_learning, "learn_from_owner_approval", lambda *a, **k: None)
    monkeypatch.setattr(sens, "is_sensitive_role", lambda r: state["sensitive"])
    yield state
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM autonomy_pending WHERE channel = 'code'")
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _run_plan(role=None):
    from core.employees.actions import run_action
    return run_action({"tool": "run_code", "channel": "code", "target": "",
                       "content": "print(1)", "subject": ""}, role=role)


def test_send_via_channel_code_dispatches(gate):
    from core.autonomy import _send_via_channel
    assert _send_via_channel("code", "", "print(2)") == "Code run: exit 0"
    assert gate["ran"] == ["print(2)"]


def test_full_mode_runs_immediately(gate):
    assert _run_plan()["status"] == "executed"
    assert gate["ran"] == ["print(1)"]


def test_semi_mode_pends_then_yes_runs(gate):
    import core.autonomy as au
    gate["mode"] = "semi"
    assert _run_plan()["status"] == "pending_approval"
    assert gate["ran"] == []
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT action_id, content FROM autonomy_pending WHERE channel = 'code' "
                    "ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert row is not None and row[1] == "print(1)"
    assert "approved and executed" in au.process_approval_response(f"YES {row[0]}")
    assert gate["ran"] == ["print(1)"]


def test_sensitive_role_forced_to_semi(gate):
    gate["sensitive"] = True
    assert _run_plan(role="legal-helper")["status"] == "pending_approval"
    assert gate["ran"] == []


# ---------------- runner: security spec tripwires ----------------

def test_spec_is_locked_down():
    s = runner.build_spec("print(1)")
    hc = s["HostConfig"]
    assert s["NetworkDisabled"] is True and hc["NetworkMode"] == "none"
    assert hc["ReadonlyRootfs"] is True and hc["Privileged"] is False
    assert hc["CapDrop"] == ["ALL"] and "no-new-privileges" in hc["SecurityOpt"]
    assert hc["Memory"] == hc["MemorySwap"] <= 256 * 1024 * 1024
    assert 0 < hc["NanoCpus"] <= 1_000_000_000 and 0 < hc["PidsLimit"] <= 128
    assert s["User"] not in ("", "0", "root", "0:0")
    assert "noexec" in hc["Tmpfs"]["/tmp"]
    for forbidden in ("Binds", "Mounts", "Devices", "CapAdd", "PidMode", "IpcMode",
                      "UsernsMode", "Links", "ExtraHosts", "Dns", "PortBindings", "VolumesFrom"):
        assert forbidden not in hc, forbidden


def test_code_travels_only_in_env_never_in_command():
    evil = "'; rm -rf / #\n$(reboot)"
    s = runner.build_spec(evil)
    assert s["Env"] == ["CODE=" + evil]
    assert evil not in " ".join(s["Cmd"])
    assert s["Cmd"][0] == "python" and "-I" in s["Cmd"]


def test_spec_ignores_everything_but_code():
    a, b = runner.build_spec("x=1"), runner.build_spec("y=2")
    a.pop("Env"), b.pop("Env")
    assert a == b


def test_demux_splits_streams():
    def frame(stream, data):
        return bytes([stream, 0, 0, 0]) + len(data).to_bytes(4, "big") + data
    out, err = runner.demux(frame(1, b"hello ") + frame(2, b"oops") + frame(1, b"world"))
    assert out == b"hello world" and err == b"oops"


def test_compose_sandbox_service_is_isolated():
    yaml = pytest.importorskip("yaml")
    svc = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["sandbox"]
    assert svc["profiles"] == ["sandbox"]          # never starts by default
    assert "env_file" not in svc                   # no API keys from .env
    assert "ports" not in svc                      # not published to the host
    assert set(svc["environment"]) <= {"SANDBOX_TOKEN", "SANDBOX_IMAGE"}
    for name, other in yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"].items():
        if name != "sandbox":
            assert not any("docker.sock" in str(v) for v in other.get("volumes", [])), name


# ---------------- runner: run_in_sandbox with a fake Docker API ----------------

class FakeDocker:
    def __init__(self, running_until_killed=False, create_status=201, start_status=204):
        self.calls, self.killed = [], False
        self.running_until_killed = running_until_killed
        self.create_status, self.start_status = create_status, start_status

    def __call__(self, method, path, body=None, timeout=30):
        self.calls.append((method, path, body))
        if path == "/containers/create":
            return self.create_status, json.dumps({"Id": "abc"}).encode()
        if path == "/containers/abc/start":
            return self.start_status, b""
        if path.endswith("/kill"):
            self.killed = True
            return 204, b""
        if path == "/containers/abc/json":
            running = self.running_until_killed and not self.killed
            return 200, json.dumps({"State": {"Running": running, "ExitCode": 0 if not running else 0,
                                              "OOMKilled": False}}).encode()
        if "/logs" in path:
            data = b"hi\n"
            return 200, bytes([1, 0, 0, 0]) + len(data).to_bytes(4, "big") + data
        if method == "DELETE":
            return 204, b""
        raise AssertionError(f"unexpected docker call {method} {path}")

    def paths(self):
        return [(m, p) for m, p, _ in self.calls]


def test_run_in_sandbox_happy_path_and_cleanup(monkeypatch):
    fd = FakeDocker()
    monkeypatch.setattr(runner, "_docker", fd)
    res = runner.run_in_sandbox("print('hi')")
    assert res["stdout"] == "hi\n" and res["exit_code"] == 0 and res["timed_out"] is False
    assert fd.calls[0][2] == runner.build_spec("print('hi')")     # exactly the fixed spec
    assert ("DELETE", "/containers/abc?force=true&v=true") in fd.paths()


def test_timeout_kills_then_cleans_up(monkeypatch):
    fd = FakeDocker(running_until_killed=True)
    monkeypatch.setattr(runner, "_docker", fd)
    monkeypatch.setattr(runner, "TIMEOUT_SECONDS", -1)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    res = runner.run_in_sandbox("while True: pass")
    assert res["timed_out"] is True and fd.killed
    assert ("DELETE", "/containers/abc?force=true&v=true") in fd.paths()


def test_failures_raise_and_still_clean_up(monkeypatch):
    fd = FakeDocker(create_status=500)
    monkeypatch.setattr(runner, "_docker", fd)
    with pytest.raises(RuntimeError):
        runner.run_in_sandbox("print(1)")
    assert not any(m == "DELETE" for m, _ in fd.paths())          # nothing was created

    fd = FakeDocker(start_status=500)
    monkeypatch.setattr(runner, "_docker", fd)
    with pytest.raises(RuntimeError):
        runner.run_in_sandbox("print(1)")
    assert ("DELETE", "/containers/abc?force=true&v=true") in fd.paths()


# ---------------- runner: HTTP layer (auth, validation, single run) ----------------

@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(runner, "TOKEN", "tok")
    monkeypatch.setattr(runner, "run_in_sandbox", lambda code: {"exit_code": 0, "stdout": code, "stderr": ""})
    srv = runner.ThreadingHTTPServer(("127.0.0.1", 0), runner.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_http_health_and_auth(server):
    assert real_requests.get(server + "/health").json() == {"status": "ok"}
    assert real_requests.post(server + "/run", json={"code": "1"}).status_code == 401
    bad = {"Authorization": "Bearer wrong"}
    assert real_requests.post(server + "/run", json={"code": "1"}, headers=bad).status_code == 401
    assert real_requests.get(server + "/nope").status_code == 404


def test_http_validation_and_success(server):
    h = {"Authorization": "Bearer tok"}
    ok = real_requests.post(server + "/run", json={"code": "print(1)"}, headers=h)
    assert ok.status_code == 200 and ok.json()["stdout"] == "print(1)"
    for body in ({"code": ""}, {"code": 5}, {"nocode": 1}, {"code": "x" * (runner.MAX_CODE_CHARS + 1)}):
        assert real_requests.post(server + "/run", json=body, headers=h).status_code in (400, 413)
    assert real_requests.post(server + "/run", data=b"not json", headers=h).status_code == 400


def test_http_busy_returns_429(server):
    h = {"Authorization": "Bearer tok"}
    assert runner._lock.acquire(blocking=False)
    try:
        assert real_requests.post(server + "/run", json={"code": "1"}, headers=h).status_code == 429
    finally:
        runner._lock.release()


def test_runner_refuses_to_start_without_token(monkeypatch):
    monkeypatch.setattr(runner, "TOKEN", "")
    with pytest.raises(SystemExit):
        runner.main()
