import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts" / "ragleap"

FAKE_DOCKER = """#!/bin/sh
echo "docker $*" >> "$FAKE_LOG"
case "$*" in
  *pg_dump*) if [ -n "$FAKE_DUMP_FAIL" ]; then exit 1; fi; echo "-- dump"; exit 0 ;;
  *psql*-At*) echo "${FAKE_ROWS-0}"; exit 0 ;;
  *psql*) cat > /dev/null; exit 0 ;;
esac
exit 0
"""
FAKE_CURL = """#!/bin/sh
echo "curl $*" >> "$FAKE_LOG"
cat > /dev/null
case "$*" in
  *"-X PUT"*) if [ -n "$FAKE_PUT_BODY" ]; then echo "$FAKE_PUT_BODY"; else echo '{"updated":["x"],"vector_status":null}'; fi ;;
  *) echo '{"status":"ok"}' ;;
esac
exit 0
"""
FAKE_GIT = """#!/bin/sh
echo "git $*" >> "$FAKE_LOG"
case "$1" in
  rev-parse) if [ -f "$FAKE_STATE/pulled" ]; then echo bbb2222; else echo aaa1111; fi ;;
  pull) if [ -n "$FAKE_PULL_FAIL" ]; then exit 1; fi; if [ -z "$FAKE_NO_CHANGE" ]; then touch "$FAKE_STATE/pulled"; fi ;;
esac
exit 0
"""
KEY_ENV = "RAGLEAP_API_KEY=abc123\n"


def run(base, args=(), env=None, env_text=KEY_ENV):
    base.mkdir(parents=True, exist_ok=True)
    bin_dir = base / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL), ("git", FAKE_GIT)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)
    proj = base / "proj"
    (proj / "db").mkdir(parents=True, exist_ok=True)
    (proj / ".git").mkdir(exist_ok=True)
    (proj / "docker-compose.yml").write_text("services: {}\n")
    (proj / "db" / "schema.sql").write_text("SELECT 1;\n")
    if env_text is not None:
        (proj / ".env").write_text(env_text)
    state = base / "state"
    state.mkdir(exist_ok=True)
    log = base / "cmd.log"
    log.touch()
    e = {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "HOME": str(base), "RAGLEAP_HOME": str(proj),
         "RAGLEAP_WAIT_TRIES": "2", "FAKE_LOG": str(log), "FAKE_STATE": str(state)}
    e.update(env or {})
    r = subprocess.run(["bash", str(CLI), *args], capture_output=True, text=True, env=e,
                       stdin=subprocess.DEVNULL, timeout=60)
    return r, proj, log.read_text().splitlines()


def test_syntax():
    assert subprocess.run(["bash", "-n", str(CLI)]).returncode == 0


def test_help_and_unknown_command(tmp_path):
    r = run(tmp_path / "a", ("help",))[0]
    assert r.returncode == 0 and "launch" in r.stdout and "update" in r.stdout
    r = run(tmp_path / "b", ("nope",))[0]
    assert r.returncode == 2 and "Unknown command" in r.stderr


def test_key_prints_the_link(tmp_path):
    r = run(tmp_path / "a", ("key",))[0]
    assert r.returncode == 0 and r.stdout.splitlines()[0] == "http://localhost:8000/office#key=abc123"
    r = run(tmp_path / "b", ("key",), env_text="OTHER=1\n")[0]
    assert r.returncode == 1 and "RAGLEAP_API_KEY" in r.stderr


def test_launch_needs_an_env_file(tmp_path):
    r, proj, log = run(tmp_path, ("launch",), env_text=None)
    assert r.returncode == 1 and not any(" up " in l for l in log)


def test_launch_plain(tmp_path):
    r, proj, log = run(tmp_path, ("launch",))
    assert r.returncode == 0, r.stderr
    assert "docker compose up -d" in log and not any("--profile" in l for l in log)
    assert "office#key=abc123" in r.stdout


def test_launch_keeps_the_ollama_profile_when_env_uses_it(tmp_path):
    r, proj, log = run(tmp_path, ("launch",), env_text=KEY_ENV + "OLLAMA_BASE_URL=http://ollama:11434/v1\n")
    assert "docker compose --profile ollama up -d" in log


def test_launch_ollama_switches_through_the_settings_api(tmp_path):
    r, proj, log = run(tmp_path, ("launch", "--ollama"))
    assert r.returncode == 0, r.stderr
    assert (proj / ".ragleap-ollama").exists()
    i_ollama = log.index("docker compose --profile ollama up -d ollama")
    i_pull = next(i for i, l in enumerate(log) if "ollama pull qwen2.5:3b" in l)
    i_up = log.index("docker compose --profile ollama up -d")
    assert i_ollama < i_pull < i_up
    put = next(l for l in log if l.startswith("curl") and "-X PUT" in l)
    assert '"LLM_PROVIDER":"ollama"' in put and '"EMBEDDING_PROVIDER":"ollama"' in put and '"EMBEDDING_DIMENSIONS":"768"' in put
    assert "abc123" not in "\n".join(log)
    assert "Chat and embeddings now use local Ollama" in r.stdout


def test_launch_ollama_leaves_embeddings_alone_when_documents_exist(tmp_path):
    r, proj, log = run(tmp_path, ("launch", "--ollama"), env={"FAKE_ROWS": "5"})
    put = next(l for l in log if "-X PUT" in l)
    assert '"LLM_PROVIDER":"ollama"' in put and "EMBEDDING_PROVIDER" not in put
    assert "Embeddings were left unchanged" in r.stdout


def test_launch_ollama_unknown_row_count_is_treated_as_unsafe(tmp_path):
    r, proj, log = run(tmp_path, ("launch", "--ollama"), env={"FAKE_ROWS": ""})
    put = next(l for l in log if "-X PUT" in l)
    assert "EMBEDDING_PROVIDER" not in put


def test_launch_ollama_when_env_already_configured(tmp_path):
    env_text = KEY_ENV + "LLM_PROVIDER=ollama\nOLLAMA_BASE_URL=http://ollama:11434/v1\n"
    r, proj, log = run(tmp_path, ("launch", "--ollama"), env_text=env_text)
    assert r.returncode == 0 and not any("-X PUT" in l for l in log)
    assert "already uses Ollama" in r.stdout


def test_launch_ollama_reports_a_vector_size_warning_and_a_failed_switch(tmp_path):
    bad = '{"updated":["x"],"vector_status":[{"table":"chunks","status":"mismatch"}]}'
    r = run(tmp_path / "a", ("launch", "--ollama"), env={"FAKE_PUT_BODY": bad})[0]
    assert "Warning" in r.stdout
    r = run(tmp_path / "b", ("launch", "--ollama"), env={"FAKE_PUT_BODY": '{"detail":"nope"}'})[0]
    assert "Could not switch automatically" in r.stdout


def test_stop_status_logs(tmp_path):
    r, proj, log = run(tmp_path / "a", ("stop",))
    assert "docker compose --profile ollama stop" in log and "data is kept" in r.stdout
    r, proj, log = run(tmp_path / "b", ("status",))
    assert "docker compose --profile ollama ps" in log and "healthy" in r.stdout
    assert run(tmp_path / "c", ("logs",))[2][-1].endswith("logs --tail 100 -f app")
    assert run(tmp_path / "d", ("logs", "worker"))[2][-1].endswith("-f worker")


def test_update_backs_up_then_pulls_then_rebuilds(tmp_path):
    r, proj, log = run(tmp_path, ("update",))
    assert r.returncode == 0, r.stderr
    i_dump = next(i for i, l in enumerate(log) if "pg_dump" in l)
    i_pull = log.index("git pull --ff-only")
    i_schema = next(i for i, l in enumerate(log) if "psql" in l and "-q" in l)
    i_build = log.index("docker compose up --build -d")
    assert i_dump < i_pull < i_schema < i_build
    backups = list((proj / "backups").glob("*.sql"))
    assert len(backups) == 1 and backups[0].stat().st_size > 0
    assert "aaa1111 -> bbb2222" in r.stdout


def test_update_when_already_current_changes_nothing(tmp_path):
    r, proj, log = run(tmp_path, ("update",), env={"FAKE_NO_CHANGE": "1"})
    assert r.returncode == 0 and "Already up to date" in r.stdout
    assert not any("up --build" in l for l in log) and not list((proj / "backups").glob("*.sql"))


def test_update_stops_when_the_backup_fails(tmp_path):
    r, proj, log = run(tmp_path, ("update",), env={"FAKE_DUMP_FAIL": "1"})
    assert r.returncode == 1 and "nothing was changed" in r.stderr
    assert "git pull --ff-only" not in log and not list((proj / "backups").glob("*.sql"))


def test_update_stops_when_the_pull_fails(tmp_path):
    r, proj, log = run(tmp_path, ("update",), env={"FAKE_PULL_FAIL": "1"})
    assert r.returncode == 1 and not any("up --build" in l for l in log)
