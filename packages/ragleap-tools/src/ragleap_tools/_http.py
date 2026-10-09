"""ragleap_tools._http - bounded stdlib HTTP for the provider modules (private).

urllib's timeout= applies to each individual socket operation, not to the
whole request, and response.read() has no size limit. A server that sends a
few bytes every few seconds, or a very large body, can therefore hold a
caller's tool-calling loop (and memory) for as long as it likes.

fetch() adds a hard TOTAL deadline and a response-size cap. The request runs
in a worker thread so control returns to the caller at the deadline. Python
cannot kill a thread: after the deadline the worker is told to stop and the
socket is shut down on a best-effort basis, so it normally exits at once, and
in the worst case within one per-operation timeout. Nothing is delivered from
an abandoned request.

urllib.request.urlopen is looked up at call time, so tests that patch it keep
working unchanged.
"""

from __future__ import annotations

import io
import socket
import threading
import urllib.error
import urllib.request
from typing import Any, Dict

DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
DEFAULT_TOTAL_TIMEOUT = 20.0
DEFAULT_OP_TIMEOUT = 15.0
MAX_ERROR_BODY_BYTES = 16_384
_CHUNK = 65_536
_THREAD_NAME = "ragleap-tools-http"


class ResponseTooLarge(urllib.error.URLError):
    """The response body exceeded the configured size cap."""

    def __init__(self, limit: int) -> None:
        super().__init__("response exceeded %d bytes" % limit)


class DeadlineExceeded(urllib.error.URLError):
    """The request did not finish within the configured total deadline."""

    def __init__(self, seconds: float) -> None:
        super().__init__("request exceeded %s seconds" % seconds)


class _Abandoned(Exception):
    pass


def validate_limits(max_response_bytes: Any, total_timeout: Any) -> None:
    if (isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int)
            or not 1_024 <= max_response_bytes <= 100_000_000):
        raise ValueError("max_response_bytes must be an int between 1024 and 100000000")
    if (isinstance(total_timeout, bool) or not isinstance(total_timeout, (int, float))
            or not 0 < total_timeout <= 3600):
        raise ValueError("total_timeout must be a number of seconds greater than 0 and at most 3600")


def _read_limited(response: Any, limit: int, abandon: threading.Event, truncate: bool = False) -> bytes:
    parts = []
    total = 0
    read1 = getattr(response, "read1", None)
    while True:
        if abandon.is_set():
            raise _Abandoned()
        want = min(_CHUNK, limit + 1 - total)
        chunk = read1(want) if callable(read1) else response.read(want)
        single = False
        if not isinstance(chunk, (bytes, bytearray)):
            # A response object without a working read1 (a simple stand-in):
            # fall back to one bounded read.
            single = True
            try:
                chunk = response.read(limit + 1 - total)
            except TypeError:
                # read() that does not accept a size: read, then cap.
                chunk = response.read()[: limit + 1 - total]
        if not chunk:
            break
        total += len(chunk)
        parts.append(bytes(chunk))
        if total > limit:
            if truncate:
                return b"".join(parts)[:limit]
            raise ResponseTooLarge(limit)
        if single:
            break
    return b"".join(parts)


def _declared_length(response: Any) -> Any:
    try:
        value = response.headers.get("Content-Length")
    except Exception:  # noqa: BLE001
        return None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _work(request: Any, max_bytes: int, op_timeout: float, abandon: threading.Event,
          holder: Dict[str, Any]) -> bytes:
    try:
        response = urllib.request.urlopen(request, timeout=op_timeout)
    except urllib.error.HTTPError as e:
        try:
            body = _read_limited(e, MAX_ERROR_BODY_BYTES, abandon, truncate=True)
        except _Abandoned:
            raise
        except Exception:  # noqa: BLE001 - an unreadable error body is just an empty one
            body = b""
        try:
            e.close()
        except Exception:  # noqa: BLE001
            pass
        raise urllib.error.HTTPError(e.filename, e.code, e.msg, e.headers, io.BytesIO(body))
    holder["response"] = response
    try:
        declared = _declared_length(response)
        if declared is not None and declared > max_bytes:
            raise ResponseTooLarge(max_bytes)
        data = _read_limited(response, max_bytes, abandon)
        if declared is not None and len(data) < declared:
            raise urllib.error.URLError("response was truncated")
        return data
    finally:
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass


def _interrupt(holder: Dict[str, Any]) -> None:
    response = holder.get("response")
    if response is None:
        return
    try:
        response.fp.raw._sock.shutdown(socket.SHUT_RDWR)  # best effort: private attributes
    except Exception:  # noqa: BLE001
        pass


def fetch(request: Any, *, max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
          total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
          op_timeout: float = DEFAULT_OP_TIMEOUT) -> bytes:
    """Perform request and return the response body as bytes.

    Raises DeadlineExceeded / ResponseTooLarge (both URLError subclasses, so
    existing `except urllib.error.URLError` handlers report them), or the
    urllib error urlopen raised. HTTPError bodies are capped at
    MAX_ERROR_BODY_BYTES and stay readable with .read().
    """
    abandon = threading.Event()
    holder: Dict[str, Any] = {}
    box: Dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = _work(request, max_bytes, op_timeout, abandon, holder)
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = e

    worker = threading.Thread(target=run, name=_THREAD_NAME, daemon=True)
    worker.start()
    worker.join(total_timeout)
    if worker.is_alive():
        abandon.set()
        _interrupt(holder)
        raise DeadlineExceeded(total_timeout)
    if "error" in box:
        raise box["error"]
    return box["value"]
