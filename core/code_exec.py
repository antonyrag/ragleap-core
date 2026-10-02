"""
Client for the isolated code-sandbox runner (see sandbox/runner.py).
Opt-in: CODE_EXEC_ENABLED=true AND SANDBOX_TOKEN set. SANDBOX_URL defaults to
the compose service. The model supplies only the Python source; it never
chooses the URL, token or any container option. Never raises.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

MAX_CODE_CHARS = 8000
MAX_RESULT_CHARS = 2000
HTTP_TIMEOUT = 45


def enabled() -> bool:
    return (os.environ.get("CODE_EXEC_ENABLED", "").strip().lower() == "true"
            and bool(os.environ.get("SANDBOX_TOKEN", "").strip()))


def run_code(code: str) -> str:
    try:
        code = (code or "").strip()
        if not code:
            return "Code run: refused (empty code)"
        if len(code) > MAX_CODE_CHARS:
            return "Code run: refused (code too long)"
        if not enabled():
            return "Code run: refused (code execution not enabled)"
        url = os.environ.get("SANDBOX_URL", "http://sandbox:8099").strip().rstrip("/")
        resp = requests.post(
            url + "/run", json={"code": code},
            headers={"Authorization": "Bearer " + os.environ["SANDBOX_TOKEN"].strip()},
            timeout=HTTP_TIMEOUT, allow_redirects=False,
        )
        if resp.status_code == 429:
            return "Code run: sandbox busy, try again"
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        d = resp.json()
        head = f"Code run: exit {d.get('exit_code')}"
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
        logger.error("Code sandbox call failed: %s", e)
        return "Code run: failed; see server logs."
