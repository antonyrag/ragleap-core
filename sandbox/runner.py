"""
RagLeap code-sandbox runner. Stdlib only, deliberately tiny.

This is the ONE component that holds the Docker socket (effectively root on
the host), so it accepts no user-controlled container options: every run
uses the fixed spec in build_spec(). Model code arrives as JSON, is passed to
the container through an environment variable (never a shell or command
line), and runs in a fresh container with: no network, read-only root, all
capabilities dropped, non-root user, memory/cpu/pids/time limits, a small
noexec tmpfs, capped logs. The container is deleted after every run.
Auth: Authorization: Bearer $SANDBOX_TOKEN. One run at a time (else 429).
"""
import hmac
import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOCKER_SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
IMAGE = os.environ.get("SANDBOX_IMAGE", "python:3.11-slim")
TOKEN = os.environ.get("SANDBOX_TOKEN", "")
PORT = int(os.environ.get("SANDBOX_PORT", "8099"))
TIMEOUT_SECONDS = max(1, min(30, int(os.environ.get("SANDBOX_TIMEOUT", "10"))))
MEMORY_BYTES = 256 * 1024 * 1024
MAX_CODE_CHARS = 8000
MAX_OUTPUT_BYTES = 16 * 1024
MAX_BODY = 16 * 1024
LABEL = "ragleap.sandbox"
BOOTSTRAP = "import os;exec(compile(os.environ.pop('CODE'),'<sandbox>','exec'))"
SHELL_BOOTSTRAP = 'c="$CMD"; unset CMD; eval "$c"'


class _Unix(http.client.HTTPConnection):
    def __init__(self, path, timeout=30):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


def _docker(method, path, body=None, timeout=30):
    c = _Unix(DOCKER_SOCKET, timeout)
    try:
        data = json.dumps(body).encode() if body is not None else None
        c.request(method, path, body=data,
                  headers={"Content-Type": "application/json"} if data is not None else {})
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


def build_spec(code, mode="python"):
    """The ONLY container spec ever used. Nothing here comes from the caller except the code."""
    return {
        "Image": IMAGE,
        "Cmd": (["sh", "-c", SHELL_BOOTSTRAP] if mode == "shell"
                else ["python", "-I", "-B", "-u", "-c", BOOTSTRAP]),
        "Env": [("CMD=" if mode == "shell" else "CODE=") + code],
        "User": "65534:65534",
        "WorkingDir": "/tmp",
        "NetworkDisabled": True,
        "Labels": {LABEL: "1"},
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "Privileged": False,
            "Memory": MEMORY_BYTES,
            "MemorySwap": MEMORY_BYTES,
            "NanoCpus": 500000000,
            "PidsLimit": 64,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=16m"},
            "Ulimits": [{"Name": "nofile", "Soft": 64, "Hard": 64},
                        {"Name": "fsize", "Soft": 16777216, "Hard": 16777216}],
            "LogConfig": {"Type": "json-file", "Config": {"max-size": "100k", "max-file": "1"}},
        },
    }


def demux(buf):
    """Split Docker's multiplexed (non-TTY) log stream into (stdout, stderr)."""
    out, err, i = bytearray(), bytearray(), 0
    while i + 8 <= len(buf):
        stream = buf[i]
        size = int.from_bytes(buf[i + 4:i + 8], "big")
        chunk = buf[i + 8:i + 8 + size]
        i += 8 + size
        (err if stream == 2 else out).extend(chunk)
    return bytes(out), bytes(err)


def run_in_sandbox(code, mode="python"):
    cid = None
    try:
        st, body = _docker("POST", "/containers/create", build_spec(code, mode))
        if st != 201:
            raise RuntimeError(f"create failed: HTTP {st} {body[:200]!r} (is {IMAGE} pulled?)")
        cid = json.loads(body)["Id"]
        st, _ = _docker("POST", f"/containers/{cid}/start")
        if st not in (204, 304):
            raise RuntimeError(f"start failed: HTTP {st}")
        start, killed = time.time(), False
        while True:
            _, body = _docker("GET", f"/containers/{cid}/json")
            state = json.loads(body)["State"]
            if not state.get("Running"):
                break
            elapsed = time.time() - start
            if elapsed > TIMEOUT_SECONDS and not killed:
                _docker("POST", f"/containers/{cid}/kill")
                killed = True
            if elapsed > TIMEOUT_SECONDS + 5:
                break
            time.sleep(0.2)
        _, logs = _docker("GET", f"/containers/{cid}/logs?stdout=1&stderr=1")
        out, err = demux(logs)
        return {
            "exit_code": state.get("ExitCode"),
            "stdout": out[:MAX_OUTPUT_BYTES].decode("utf-8", "replace"),
            "stderr": err[:MAX_OUTPUT_BYTES].decode("utf-8", "replace"),
            "timed_out": killed,
            "oom": bool(state.get("OOMKilled")),
        }
    finally:
        if cid:
            try:
                _docker("DELETE", f"/containers/{cid}?force=true&v=true")
            except Exception:
                pass


def cleanup_orphans():
    try:
        flt = urllib.parse.quote(json.dumps({"label": [LABEL + "=1"]}))
        _, body = _docker("GET", f"/containers/json?all=1&filters={flt}")
        for c in json.loads(body):
            _docker("DELETE", f"/containers/{c['Id']}?force=true&v=true")
    except Exception as e:
        print(f"orphan cleanup skipped: {e}", flush=True)


_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def log_message(self, *a):  # never log request bodies or code
        pass

    def _reply(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._reply(200, {"status": "ok"}) if self.path == "/health" else self._reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            return self._reply(404, {"error": "not found"})
        want = ("Bearer " + TOKEN).encode()
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), want):
            return self._reply(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return self._reply(413, {"error": "bad body size"})
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or ("code" in payload) == ("shell" in payload):
                raise ValueError  # exactly one of "code" / "shell"
            key = "shell" if "shell" in payload else "code"
            code = payload[key]
            if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS or "\x00" in code:
                raise ValueError
        except Exception:
            return self._reply(400, {"error": "body must be JSON {\"code\": \"<=8000 chars\"}"})
        if not _lock.acquire(blocking=False):
            return self._reply(429, {"error": "busy"})
        try:
            self._reply(200, run_in_sandbox(code, "shell") if key == "shell" else run_in_sandbox(code))
        except Exception as e:
            print(f"run failed: {e}", flush=True)
            self._reply(500, {"error": "sandbox error"})
        finally:
            _lock.release()


def main():
    if not TOKEN:
        print("SANDBOX_TOKEN is not set; refusing to start.", flush=True)
        sys.exit(1)
    cleanup_orphans()
    print(f"sandbox runner listening on :{PORT} (image {IMAGE}, timeout {TIMEOUT_SECONDS}s)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
