"""
The sandbox runner ships in its own image instead of being bind-mounted from the folder
compose runs in (which depends on whichever branch happens to be checked out there).
Tripwires so that cannot silently regress.
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sandbox_service():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["sandbox"]


def test_sandbox_is_built_not_bind_mounted():
    svc = sandbox_service()
    assert svc["build"] == "./sandbox" and svc["image"] == "ragleap-core-sandbox"
    vols = [str(v) for v in svc.get("volumes", [])]
    assert vols == ["/var/run/docker.sock:/var/run/docker.sock"]
    assert svc["read_only"] is True and svc["cap_drop"] == ["ALL"] and "env_file" not in svc


def test_dockerfile_copies_the_runner_and_installs_nothing():
    lines = [l.strip() for l in (ROOT / "sandbox" / "Dockerfile").read_text().splitlines()
             if l.strip() and not l.strip().startswith("#")]
    assert lines[0] == "FROM python:3.11-slim"
    assert "COPY runner.py /runner.py" in lines and 'CMD ["python", "-u", "/runner.py"]' in lines
    assert not any(l.split()[0].upper() in ("RUN", "ADD", "ENV", "ARG", "USER", "EXPOSE") for l in lines)


def test_build_context_holds_only_the_dockerfile_and_the_runner():
    files = {p.name for p in (ROOT / "sandbox").iterdir() if p.is_file()}
    assert files == {"Dockerfile", "runner.py"}
