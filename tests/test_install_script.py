import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "install.sh"

FAKE_DOCKER = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
if [ -n "$FAKE_DOCKER_DOWN" ] && [ "$1" = "info" ]; then exit 1; fi
if [ "$1" = "volume" ] && [ "$2" = "ls" ]; then
  if [ -n "$FAKE_VOLUME" ]; then echo "$FAKE_VOLUME"; fi
  exit 0
fi
exit 0
"""
FAKE_CURL = "#!/bin/sh\necho '{\"status\":\"ok\"}'\nexit 0\n"
FAKE_GIT = "#!/bin/sh\necho \"git called: $@\" >> \"$FAKE_LOG\"\nexit 1\n"


def run(base, args=(), env=None, env_text=None):
    base.mkdir(parents=True, exist_ok=True)
    bin_dir = base / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL), ("git", FAKE_GIT)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)
    proj = base / "proj"
    if not proj.exists():
        proj.mkdir()
        shutil.copy(ROOT / ".env.example", proj / ".env.example")
        (proj / "docker-compose.yml").write_text("services: {}\n")
    if env_text is not None:
        (proj / ".env").write_text(env_text)
    log = base / "docker.log"
    log.touch()
    e = {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "HOME": str(base), "RAGLEAP_DIR": str(proj),
         "RAGLEAP_NONINTERACTIVE": "1", "RAGLEAP_WAIT_TRIES": "2", "FAKE_LOG": str(log)}
    e.update(env or {})
    r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=e,
                       stdin=subprocess.DEVNULL, start_new_session=True, timeout=60)
    return r, proj, log.read_text()


def envfile(proj):
    d = {}
    for line in (proj / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            d[k] = v
    return d


def test_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_fresh_gemini_install(tmp_path):
    r, proj, log = run(tmp_path, env={"RAGLEAP_PROVIDER": "gemini", "GEMINI_API_KEY": "gk-test-123"})
    assert r.returncode == 0, r.stderr
    e = envfile(proj)
    assert re.fullmatch(r"[0-9a-f]{48}", e["RAGLEAP_API_KEY"])
    assert re.fullmatch(r"[0-9a-f]{48}", e["SANDBOX_TOKEN"])
    assert re.fullmatch(r"[0-9a-f]{24}", e["POSTGRES_PASSWORD"])
    Fernet(e["ADDON_ENCRYPTION_KEY"].encode())
    assert e["GEMINI_API_KEY"] == "gk-test-123"
    assert stat.S_IMODE((proj / ".env").stat().st_mode) == 0o600
    assert "http://localhost:8000/office#key=" + e["RAGLEAP_API_KEY"] in r.stdout
    assert "compose up --build -d" in log and "git called" not in log and "ollama" not in log
    assert "gk-test-123" not in r.stdout + r.stderr


@pytest.mark.parametrize("how", ["flag", "env"])
def test_ollama_install(tmp_path, how):
    kw = {"args": ("--ollama",)} if how == "flag" else {"env": {"RAGLEAP_PROVIDER": "ollama"}}
    r, proj, log = run(tmp_path, **kw)
    assert r.returncode == 0, r.stderr
    e = envfile(proj)
    assert e["LLM_PROVIDER"] == "ollama" and e["OLLAMA_MODEL"] == "qwen2.5:3b"
    assert e["OLLAMA_BASE_URL"] == "http://ollama:11434/v1"
    assert e["EMBEDDING_PROVIDER"] == "ollama" and e["OLLAMA_EMBEDDING_MODEL"] == "nomic-embed-text"
    assert e["EMBEDDING_DIMENSIONS"] == "768" and e["GEMINI_API_KEY"] == ""
    assert "compose --profile ollama up --build -d" in log
    assert "ollama pull qwen2.5:3b" in log and "ollama pull nomic-embed-text" in log
    assert "slowly" in r.stdout


def test_existing_env_is_never_changed(tmp_path):
    text = "RAGLEAP_API_KEY=abc123\nGEMINI_API_KEY=mine\nSOMETHING=else\n"
    r, proj, log = run(tmp_path, env={"RAGLEAP_PROVIDER": "ollama"}, env_text=text)
    assert r.returncode == 0, r.stderr
    assert (proj / ".env").read_text() == text
    assert "Keeping your existing .env" in r.stdout and "office#key=abc123" in r.stdout
    assert "--profile ollama" not in log


def test_existing_ollama_setup_keeps_its_service_and_models(tmp_path):
    text = ("RAGLEAP_API_KEY=k\nOLLAMA_BASE_URL=http://ollama:11434/v1\nOLLAMA_MODEL=m1\n"
            "OLLAMA_EMBEDDING_MODEL=e1\n")
    r, proj, log = run(tmp_path, env_text=text)
    assert r.returncode == 0, r.stderr
    assert "--profile ollama" in log and "ollama pull m1" in log and "ollama pull e1" in log


def test_existing_database_volume_keeps_its_password(tmp_path):
    r, proj, log = run(tmp_path, env={"RAGLEAP_PROVIDER": "skip", "FAKE_VOLUME": "proj_ragleap_core_data"})
    assert r.returncode == 0, r.stderr
    assert "POSTGRES_PASSWORD" not in envfile(proj)


def test_no_choice_and_no_terminal_skips_the_ai(tmp_path):
    r, proj, log = run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert envfile(proj)["GEMINI_API_KEY"] == "" and "Settings" in r.stdout and "--profile" not in log


def test_docker_not_running(tmp_path):
    r, proj, log = run(tmp_path, env={"FAKE_DOCKER_DOWN": "1"})
    assert r.returncode == 1 and "not running" in r.stderr and not (proj / ".env").exists()


def test_unknown_option_and_bad_provider(tmp_path):
    assert run(tmp_path / "a", args=("--nope",))[0].returncode == 2
    r = run(tmp_path / "b", env={"RAGLEAP_PROVIDER": "nope"})[0]
    assert r.returncode == 1 and "must be" in r.stderr


def test_secrets_differ_between_installs(tmp_path):
    a = envfile(run(tmp_path / "a", env={"RAGLEAP_PROVIDER": "skip"})[1])
    b = envfile(run(tmp_path / "b", env={"RAGLEAP_PROVIDER": "skip"})[1])
    for k in ("RAGLEAP_API_KEY", "ADDON_ENCRYPTION_KEY", "SANDBOX_TOKEN", "POSTGRES_PASSWORD"):
        assert a[k] != b[k], k


def test_ollama_service_is_internal_only():
    text = (ROOT / "docker-compose.yml").read_text()
    block = text.split("  ollama:\n")[1].split("\n\n")[0]
    assert 'profiles: ["ollama"]' in block and "ollama/ollama" in block and "ports" not in block
    assert "ragleap_core_ollama:" in text.split("\nvolumes:\n")[-1]


def test_docs_match_the_installer():
    readme = (ROOT / "README.md").read_text()
    assert "will pause after cloning" not in readme and "--ollama" in readme
    assert "no login of its own" not in (ROOT / ".env.example").read_text()


def test_ollama_models_are_ready_before_ragleap_starts(tmp_path):
    r, proj, log = run(tmp_path, args=("--ollama",))
    lines = log.splitlines()
    i_ollama = next(i for i, l in enumerate(lines) if l.endswith("up -d ollama"))
    i_pull = next(i for i, l in enumerate(lines) if "ollama pull qwen2.5:3b" in l)
    i_up = next(i for i, l in enumerate(lines) if l.endswith("up --build -d"))
    assert i_ollama < i_pull < i_up


def test_installer_installs_the_ragleap_command(tmp_path):
    r, proj, log = run(tmp_path, env={"RAGLEAP_PROVIDER": "skip"})
    shim = tmp_path / ".local" / "bin" / "ragleap"
    assert shim.exists() and os.access(shim, os.X_OK)
    body = shim.read_text()
    assert str(proj) in body and "scripts/ragleap" in body
    assert "PATH" in r.stdout
