"""Folder staging in the sandbox runner (POST /stage): the fixed container specs (tripwires), the copier and the
pruner run for real on temporary folders, the endpoint logic with a fake Docker, and the compose wiring.
No Docker, network or database is used."""
import hashlib
import http.client
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sandbox_runner_stage", ROOT / "sandbox" / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

KNOW = {"name": "docs", "path": "/data/docs", "mode": "read", "purpose": "knowledge", "expires": None}


# ---------------- the container specs (tripwires) ----------------

def _same_hardening(spec):
    base = runner.build_spec("")
    host = dict(spec["HostConfig"])
    for key in ("Mounts", "Ulimits"):
        host.pop(key, None)
    base_host = dict(base["HostConfig"])
    base_host.pop("Ulimits")
    assert host == base_host                               # every other limit and flag unchanged
    assert spec["NetworkDisabled"] is True and spec["HostConfig"]["NetworkMode"] == "none"
    assert spec["HostConfig"]["ReadonlyRootfs"] is True and spec["HostConfig"]["CapDrop"] == ["ALL"]
    assert spec["HostConfig"]["Privileged"] is False and "CapAdd" not in spec["HostConfig"]
    assert "Binds" not in spec["HostConfig"]


def test_stage_spec_is_the_hardened_spec_plus_a_read_only_folder_and_the_staging_volume():
    spec = runner.build_stage_spec(KNOW)
    _same_hardening(spec)
    assert spec["User"] == "65534:65534" and spec["Cmd"] == ["python", "-I", "-B", "-c", runner.STAGER]
    assert spec["HostConfig"]["Mounts"] == [
        {"Type": "bind", "Source": "/data/docs", "Target": "/data", "ReadOnly": True},
        {"Type": "volume", "Source": "ragleap_core_staging", "Target": "/staging", "ReadOnly": False,
         "VolumeOptions": {"NoCopy": True}}]
    assert sorted(e.split("=", 1)[0] for e in spec["Env"]) == ["GRANT", "MAXC", "MAXF", "MAXN", "MAXT"]
    fsize = [u for u in spec["HostConfig"]["Ulimits"] if u["Name"] == "fsize"][0]
    assert fsize["Hard"] > runner.STAGE_MAX_FILE            # a file at the limit can be written


def test_write_grants_are_still_mounted_read_only_for_staging():
    assert runner.build_stage_spec(dict(KNOW, mode="write"))["HostConfig"]["Mounts"][0]["ReadOnly"] is True


def test_prune_and_prepare_specs_mount_only_the_staging_volume():
    prune = runner.build_prune_spec(["b", "a"])
    _same_hardening(prune)
    assert prune["User"] == "65534:65534" and prune["Env"] == ['KEEP=["a", "b"]']
    assert [m["Target"] for m in prune["HostConfig"]["Mounts"]] == ["/staging"]
    prep = runner.build_prepare_spec()
    _same_hardening(prep)
    assert prep["User"] == "0:0" and prep["Cmd"][-1] == runner.PREPARE and prep["Env"] == []
    assert [m["Target"] for m in prep["HostConfig"]["Mounts"]] == ["/staging"]


def test_the_extension_list_matches_the_document_formats_the_app_accepts():
    parsers = pytest.importorskip("ragleap.parsers")
    assert set(runner.STAGE_EXTENSIONS) == set(parsers.SUPPORTED_EXTENSIONS)


# ---------------- the copier and the pruner, run for real ----------------

@pytest.fixture
def area(tmp_path):
    src, out = tmp_path / "src", tmp_path / "staging"
    (src / "sub" / "deep").mkdir(parents=True)
    (src / ".git").mkdir()
    out.mkdir()
    (src / "a.txt").write_text("hello\n")
    (src / "sub" / "b.md").write_text("# b")
    (src / "sub" / "deep" / "c.pdf").write_bytes(b"%PDF-1.4 fake")
    for secret in (".env", "id_rsa", "cert.pem", "notes.exe", ".git/config"):
        (src / secret).write_text("SECRET=1")
    os.symlink("/etc/passwd", src / "link.txt")
    os.symlink("/etc", src / "etclink")
    return src, out


def stage(area, grant="docs", **limits):
    src, out = area
    env = dict(os.environ, RL_DATA=str(src), RL_STAGING=str(out), GRANT=grant,
               **{k: str(v) for k, v in limits.items()})
    code = runner.STAGER if grant else ""
    p = subprocess.run([sys.executable, "-I", "-B", "-c", code], env=env, capture_output=True, text=True, timeout=60)
    return p.returncode, json.loads(p.stdout or "{}")


def manifest(area, grant="docs"):
    return json.loads((area[1] / ".manifests" / (grant + ".json")).read_text())


def staged_names(area, grant="docs"):
    base = area[1] / grant
    return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())


def test_allowed_files_are_copied_with_a_manifest(area):
    code, res = stage(area)
    assert code == 0 and res["files"] == 3 and res["copied"] == 3, res
    assert staged_names(area) == ["a.txt", "sub/b.md", "sub/deep/c.pdf"]
    m = manifest(area)
    assert [f["path"] for f in m["files"]] == ["a.txt", "sub/b.md", "sub/deep/c.pdf"]
    assert m["files"][0]["sha256"] == hashlib.sha256(b"hello\n").hexdigest() and m["files"][0]["size"] == 6
    assert (area[1] / "docs" / "a.txt").read_text() == "hello\n"


def test_secrets_symlinks_and_other_types_are_never_staged(area):
    _, res = stage(area)
    names = " ".join(staged_names(area))
    for bad in (".env", "id_rsa", "cert.pem", "notes.exe", "config", "passwd", "link.txt"):
        assert bad not in names, bad
    assert res["skipped"]["symlink"] == 2 and res["skipped"]["extension"] == 1
    assert res["skipped"]["denied"] >= 4
    assert "SECRET" not in json.dumps(manifest(area)) and "/etc" not in json.dumps(manifest(area))


def test_unchanged_files_are_not_copied_again_and_changes_are_picked_up(area):
    stage(area)
    assert stage(area)[1]["copied"] == 0
    f = area[0] / "a.txt"
    f.write_text("changed text\n")
    os.utime(f, (1_700_000_000, 1_700_000_000))
    _, res = stage(area)
    assert res["copied"] == 1
    assert (area[1] / "docs" / "a.txt").read_text() == "changed text\n"
    assert [x["sha256"] for x in manifest(area)["files"] if x["path"] == "a.txt"] == [
        hashlib.sha256(b"changed text\n").hexdigest()]


def test_a_deleted_source_file_leaves_staging_and_empty_folders_go(area):
    stage(area)
    (area[0] / "sub" / "deep" / "c.pdf").unlink()
    _, res = stage(area)
    assert res["removed"] == 1 and staged_names(area) == ["a.txt", "sub/b.md"]
    assert not (area[1] / "docs" / "sub" / "deep").exists()
    assert [f["path"] for f in manifest(area)["files"]] == ["a.txt", "sub/b.md"]


def test_the_copy_cap_resumes_on_the_next_run(area):
    for i in range(5):
        (area[0] / ("n%d.txt" % i)).write_text("x%d" % i)
    seen = [stage(area, MAXC=3)[1] for _ in range(3)]
    assert [r["copied"] for r in seen] == [3, 3, 2] and seen[0]["pending"] == 5 and seen[2]["pending"] == 0
    assert len(staged_names(area)) == 8 and manifest(area)["pending"] == 0


def test_total_caps_mark_the_run_truncated(area):
    _, res = stage(area, MAXN=2)
    assert res["files"] == 2 and res["truncated"] is True
    _, res = stage(area, MAXN=100, MAXT=10)
    assert res["bytes"] <= 10 and res["truncated"] is True and len(staged_names(area)) == res["files"]


def test_oversized_files_are_skipped(area):
    _, res = stage(area, MAXF=8)
    assert res["skipped"]["too_large"] == 1 and "sub/deep/c.pdf" not in staged_names(area)


@pytest.mark.parametrize("name", ["../x", "a/b", ".manifests"])
def test_a_bad_grant_name_is_refused(area, name):
    code, res = stage(area, grant=name)
    assert code == 2 and "error" in res


def test_the_pruner_removes_staging_of_grants_that_are_gone(tmp_path):
    for g in ("a", "b"):
        (tmp_path / g).mkdir()
        (tmp_path / g / "f.txt").write_text("x")
        (tmp_path / ".manifests").mkdir(exist_ok=True)
        (tmp_path / ".manifests" / (g + ".json")).write_text("{}")
    env = dict(os.environ, RL_STAGING=str(tmp_path), KEEP='["a"]')
    p = subprocess.run([sys.executable, "-I", "-B", "-c", runner.PRUNER], env=env, capture_output=True, text=True)
    assert json.loads(p.stdout) == {"op": "prune", "removed": ["b"]}
    assert sorted(x.name for x in tmp_path.iterdir()) == [".manifests", "a"]
    assert sorted(x.name for x in (tmp_path / ".manifests").iterdir()) == ["a.json"]


# ---------------- the endpoint, with a fake Docker ----------------

@pytest.fixture
def srv(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "TOKEN", "tok")
    f = tmp_path / "grants.json"
    f.write_text(json.dumps({"grants": [
        {"name": "docs", "path": "/data/docs", "mode": "read", "purpose": "knowledge"},
        {"name": "kb2", "path": "/data/kb2", "mode": "read", "purpose": "knowledge"},
        {"name": "tools", "path": "/data/tools", "mode": "read", "purpose": "use"},
        {"name": "old", "path": "/data/old", "mode": "read", "purpose": "knowledge", "expires": "2000-01-01T00:00:00Z"},
    ]}))
    monkeypatch.setattr(runner, "GRANTS_FILE", str(f))
    monkeypatch.setenv("COMPUTER_CONTROL", "true")
    calls = []

    def fake_run(spec, timeout=None):
        calls.append((spec, timeout))
        cmd = spec["Cmd"][-1]
        if cmd == runner.PREPARE:
            out = ""
        elif cmd == runner.PRUNER:
            out = json.dumps({"op": "prune", "removed": ["gone"]})
        else:
            name = [e for e in spec["Env"] if e.startswith("GRANT=")][0][6:]
            out = json.dumps({"op": "stage", "grant": name, "files": 2, "copied": 2, "removed": 0, "bytes": 9,
                              "pending": 0, "truncated": False, "skipped": {}})
        return {"exit_code": 0, "stdout": out, "stderr": "", "timed_out": False, "oom": False}

    monkeypatch.setattr(runner, "_run_spec", fake_run)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), runner.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def call(path, body=None, token="tok"):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        c.request("POST", path, body=json.dumps({} if body is None else body), headers=headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, json.loads(data or b"{}")

    yield call, calls
    httpd.shutdown()
    httpd.server_close()


def test_stage_needs_the_token_and_the_switch(srv, monkeypatch):
    call, calls = srv
    assert call("/stage", token=None)[0] == 401 and call("/stage", token="wrong")[0] == 401
    monkeypatch.setenv("COMPUTER_CONTROL", "false")
    assert call("/stage") == (403, {"error": "computer control is off"})
    assert calls == []


def test_stage_without_a_name_stages_every_active_knowledge_grant_then_prunes(srv):
    call, calls = srv
    status, body = call("/stage")
    assert status == 200 and body["ok"] is True and body["pruned"] == ["gone"]
    assert [r["grant"] for r in body["results"]] == ["docs", "kb2"]
    kinds = [c[0]["Cmd"][-1] for c in calls]
    assert kinds[0] == runner.PREPARE and kinds[-1] == runner.PRUNER and len(kinds) == 4
    assert calls[1][0] == runner.build_stage_spec(runner.active_grants()[0]) and calls[1][1] == runner.STAGE_TIMEOUT
    assert calls[-1][0] == runner.build_prune_spec(["docs", "kb2"])     # "use" and expired grants are not kept


def test_stage_with_a_name_stages_only_that_grant_and_still_prunes(srv):
    call, calls = srv
    status, body = call("/stage", {"grant": "kb2"})
    assert status == 200 and [r["grant"] for r in body["results"]] == ["kb2"]
    assert calls[1][0]["HostConfig"]["Mounts"][0]["Source"] == "/data/kb2"
    assert calls[-1][0] == runner.build_prune_spec(["docs", "kb2"])


@pytest.mark.parametrize("name", ["tools", "old", "nope"])
def test_use_expired_and_unknown_grants_are_not_staged(srv, name):
    call, calls = srv
    assert call("/stage", {"grant": name})[0] == 404 and calls == []
    assert call("/stage", {"grant": 5})[0] == 400 and call("/stage", [1])[0] == 400


def test_extra_fields_in_the_request_change_nothing(srv):
    call, calls = srv
    call("/stage", {"grant": "docs", "image": "evil", "mount": "/", "Mounts": [{"Source": "/"}], "path": "/etc"})
    assert calls[1][0] == runner.build_stage_spec(runner.active_grants()[0])


def test_failures_are_reported_without_details(srv, monkeypatch):
    call, calls = srv
    real = runner._run_spec

    def failing(spec, timeout=None):
        if spec["Cmd"][-1] == runner.STAGER:
            return {"exit_code": 3, "stdout": json.dumps({"error": "could not stage: OSError"}), "stderr": "",
                    "timed_out": False, "oom": False}
        return real(spec, timeout)

    monkeypatch.setattr(runner, "_run_spec", failing)
    status, body = call("/stage", {"grant": "docs"})
    assert status == 200 and body["ok"] is False
    assert body["results"] == [{"grant": "docs", "ok": False, "error": "could not stage: OSError"}]
    monkeypatch.setattr(runner, "_run_spec", lambda spec, timeout=None: {
        "exit_code": 1, "stdout": "", "stderr": "boom", "timed_out": False, "oom": False})
    assert call("/stage") == (200, {"ok": False, "error": "the staging volume is not ready"})


def test_the_busy_lock_applies_to_stage(srv):
    call, calls = srv
    assert runner._lock.acquire(blocking=False)
    try:
        assert call("/stage")[0] == 429
    finally:
        runner._lock.release()
    assert calls == []


# ---------------- the compose wiring ----------------

def test_compose_only_the_app_mounts_staging_and_only_read_only():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert doc["volumes"]["ragleap_core_staging"] == {"name": runner.STAGING_VOLUME}
    for name, svc in doc["services"].items():
        mounts = [str(v) for v in svc.get("volumes", []) if "staging" in str(v)]
        assert mounts == (["ragleap_core_staging:/staging:ro"] if name == "app" else []), name
    assert doc["services"]["sandbox"]["volumes"] == ["/var/run/docker.sock:/var/run/docker.sock", "./grants:/grants:ro"]
