"""Real-Docker tests for folder staging (sandbox/runner.py, POST /stage).

Off unless RAGLEAP_DOCKER_TESTS=1 (needs Docker and python:3.11-slim); they run in CI (core-tests). The grant lookup
and the kill switch are replaced and a throwaway staging volume is used; everything else is the real runner code.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import tempfile
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RAGLEAP_DOCKER_TESTS") != "1", reason="set RAGLEAP_DOCKER_TESTS=1 (needs Docker and python:3.11-slim)")

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sandbox_runner_stage_docker", ROOT / "sandbox" / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


@pytest.fixture
def stage_env(monkeypatch):
    assert os.path.exists(runner.DOCKER_SOCKET), "no Docker socket at " + runner.DOCKER_SOCKET
    vol = "rl-stage-test-" + uuid.uuid4().hex[:10]
    base = pathlib.Path(tempfile.mkdtemp(prefix="rl-stage-"))
    os.chmod(base, 0o755)                      # the container runs as uid 65534
    (base / "sub").mkdir()
    for rel, text in (("a.txt", "hello\n"), ("sub/b.md", "# b"), (".env", "SECRET=1"), ("id_rsa", "KEY"), ("x.exe", "MZ")):
        (base / rel).write_text(text)
        os.chmod(base / rel, 0o644)
    os.chmod(base / "sub", 0o755)
    os.symlink("/etc/passwd", base / "link.txt")
    grant = {"name": "docs", "path": str(base), "mode": "read", "purpose": "knowledge", "expires": None}
    monkeypatch.setattr(runner, "STAGING_VOLUME", vol)
    monkeypatch.setattr(runner, "computer_control_on", lambda: True)
    monkeypatch.setattr(runner, "active_grants", lambda now=None: [grant])
    yield base
    runner._docker("DELETE", "/volumes/" + vol + "?force=true")
    shutil.rmtree(base, ignore_errors=True)


def view(code):
    """Run code in a container like the app sees it: uid 10001, the staging volume mounted read-only."""
    spec = runner.build_spec("")
    spec["User"] = "10001:10001"
    spec["Cmd"] = ["python", "-I", "-B", "-c", code]
    spec["Env"] = []
    spec["HostConfig"]["Mounts"] = [dict(runner._staging_mount(), ReadOnly=True)]
    return runner._run_spec(spec)


LIST = ("import json,os\n"
        "r=[]\n"
        "for d,_,fs in os.walk('/staging'):\n"
        "    for f in fs:\n"
        "        p=os.path.join(d,f); r.append([p, os.stat(p).st_uid])\n"
        "print(json.dumps(sorted(r)))\n")


def test_stage_copies_allowed_files_and_the_app_can_read_but_not_write_them(stage_env):
    status, body = runner.stage_op({})
    assert status == 200 and body["ok"] is True, body
    assert body["results"][0]["files"] == 2 and body["results"][0]["copied"] == 2, body
    res = view(LIST)
    assert res["exit_code"] == 0, res
    listed = dict(json.loads(res["stdout"]))
    assert sorted(listed) == ["/staging/.manifests/docs.json", "/staging/docs/a.txt", "/staging/docs/sub/b.md"], listed
    assert listed["/staging/docs/a.txt"] == 65534                      # written by the unprivileged copier
    read = view("import json;m=json.load(open('/staging/.manifests/docs.json'));"
                "print(m['files'][0]['path'], open('/staging/docs/a.txt').read().strip())")
    assert read["stdout"].strip() == "a.txt hello", read
    write = view("open('/staging/docs/new.txt','w').write('x')")
    assert write["exit_code"] != 0 and "Read-only file system" in write["stderr"], write


def test_changes_deletions_and_removed_grants_are_followed(stage_env):
    runner.stage_op({})
    status, body = runner.stage_op({})
    assert body["results"][0]["copied"] == 0, body                      # nothing changed
    (stage_env / "a.txt").write_text("changed\n")
    os.utime(stage_env / "a.txt", (1_700_000_000, 1_700_000_000))
    (stage_env / "sub" / "b.md").unlink()
    body = runner.stage_op({})[1]
    assert body["results"][0]["copied"] == 1 and body["results"][0]["removed"] == 1, body
    names = [p for p, _ in json.loads(view(LIST)["stdout"])]
    assert names == ["/staging/.manifests/docs.json", "/staging/docs/a.txt"], names
    runner.active_grants = lambda now=None: []                          # the grant is gone
    body = runner.stage_op({})[1]
    assert body["pruned"] == ["docs"], body
    assert json.loads(view(LIST)["stdout"]) == []
