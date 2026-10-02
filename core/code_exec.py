"""
Client for the isolated sandbox runner (see sandbox/runner.py): run_code
(Python) and run_shell (sh). Each is separately opt-in:
  CODE_EXEC_ENABLED=true  /  SHELL_EXEC_ENABLED=true   AND   SANDBOX_TOKEN set.
SANDBOX_URL defaults to the compose service. The model supplies only the
source/command text; it never chooses the URL, token or any container
option. Never raises.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

MAX_CODE_CHARS = 8000
MAX_RESULT_CHARS = 2000
HTTP_TIMEOUT = 45


def _flag(name: str) -> bool:
    return (os.environ.get(name, "").strip().lower() == "true"
            and bool(os.environ.get("SANDBOX_TOKEN", "").strip()))


def enabled() -> bool:
    return _flag("CODE_EXEC_ENABLED")


def shell_enabled() -> bool:
    return _flag("SHELL_EXEC_ENABLED")


def _execute(label: str, key: str, text: str, is_enabled) -> str:
    try:
        text = (text or "").strip()
        if not text:
            return f"{label}: refused (empty)"
        if len(text) > MAX_CODE_CHARS:
            return f"{label}: refused (too long)"
        if "\x00" in text:
            return f"{label}: refused (invalid characters)"
        if not is_enabled():
            return f"{label}: refused (not enabled)"
        url = os.environ.get("SANDBOX_URL", "http://sandbox:8099").strip().rstrip("/")
        resp = requests.post(
            url + "/run", json={key: text},
            headers={"Authorization": "Bearer " + os.environ["SANDBOX_TOKEN"].strip()},
            timeout=HTTP_TIMEOUT, allow_redirects=False,
        )
        if resp.status_code == 429:
            return f"{label}: sandbox busy, try again"
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        d = resp.json()
        head = f"{label}: exit {d.get('exit_code')}"
        if d.get("timed_out"):
            head += " (timed out)"
        if d.get("oom"):
            head += " (out of memory)"
        parts = [head]
        if d.get("stdout"):
            parts.append("stdout:\n" + d["stdout"])
        if d.get("stderr"):
            parts.append("stderr:\n" + d["stderr"])
        return "\n".join(parts)[:MAX_RESULT_CHARS]
    except Exception as e:
        logger.error("%s sandbox call failed: %s", label, e)
        return f"{label}: failed; see server logs."


def run_code(code: str) -> str:
    return _execute("Code run", "code", code, enabled)


def run_shell(command: str) -> str:
    return _execute("Shell run", "shell", command, shell_enabled)
