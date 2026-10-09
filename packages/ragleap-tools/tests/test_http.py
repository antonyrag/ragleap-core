"""Tests for ragleap_tools._http.fetch against a real local HTTP server."""

import socket
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from ragleap_tools._http import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_OP_TIMEOUT,
    DEFAULT_TOTAL_TIMEOUT,
    MAX_ERROR_BODY_BYTES,
    DeadlineExceeded,
    ResponseTooLarge,
    fetch,
    validate_limits,
)


def req(server):
    return urllib.request.Request(server.url)


def workers():
    return [t for t in threading.enumerate() if t.name == "ragleap-tools-http"]


def test_defaults_are_the_documented_values():
    assert (DEFAULT_MAX_RESPONSE_BYTES, DEFAULT_TOTAL_TIMEOUT, DEFAULT_OP_TIMEOUT) == (1_048_576, 20.0, 15.0)
    assert MAX_ERROR_BODY_BYTES == 16_384


def test_returns_the_body(server):
    server.payload = b'{"a": 1}'
    assert fetch(req(server), max_bytes=1024, total_timeout=5) == b'{"a": 1}'


def test_exactly_at_the_limit_passes_and_one_over_fails(server):
    server.payload = b"a" * 2048
    assert len(fetch(req(server), max_bytes=2048, total_timeout=5)) == 2048
    server.payload = b"a" * 2049
    with pytest.raises(ResponseTooLarge):
        fetch(req(server), max_bytes=2048, total_timeout=5)


def test_declared_oversize_is_rejected_without_waiting_for_the_body(server):
    server.mode = "declared_big_stall"
    t0 = time.monotonic()
    with pytest.raises(ResponseTooLarge):
        fetch(req(server), max_bytes=1_048_576, total_timeout=5)
    assert time.monotonic() - t0 < 2


def test_oversize_with_content_length(server):
    server.mode = "big"
    with pytest.raises(ResponseTooLarge):
        fetch(req(server), max_bytes=1_048_576, total_timeout=5)


def test_oversize_chunked_without_content_length(server):
    server.mode = "bigchunked"
    with pytest.raises(ResponseTooLarge):
        fetch(req(server), max_bytes=1_048_576, total_timeout=5)


def test_chunked_body_within_the_limit_is_decoded(server):
    server.mode = "bigchunked"
    assert len(fetch(req(server), max_bytes=4 * 1024 * 1024, total_timeout=10)) == 32 * 65536


def test_slow_drip_body_hits_the_total_deadline(server):
    server.mode = "drip"
    t0 = time.monotonic()
    with pytest.raises(DeadlineExceeded):
        fetch(req(server), max_bytes=1_048_576, total_timeout=0.6, op_timeout=5)
    assert 0.5 <= time.monotonic() - t0 < 2.5


def test_stalled_body_hits_the_deadline(server):
    server.mode = "stall"
    t0 = time.monotonic()
    with pytest.raises(DeadlineExceeded):
        fetch(req(server), max_bytes=1024, total_timeout=0.6, op_timeout=5)
    assert time.monotonic() - t0 < 2.5


def test_server_that_never_answers_hits_the_deadline(server):
    server.mode = "headdelay"
    t0 = time.monotonic()
    with pytest.raises(DeadlineExceeded):
        fetch(req(server), max_bytes=1024, total_timeout=0.5, op_timeout=5)
    assert time.monotonic() - t0 < 2.5


def test_worker_thread_exits_soon_after_the_deadline(server):
    server.mode = "drip"
    with pytest.raises(DeadlineExceeded):
        fetch(req(server), max_bytes=1_048_576, total_timeout=0.4, op_timeout=5)
    deadline = time.monotonic() + 3
    while workers() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert workers() == []


def test_error_types_are_urlerrors_with_readable_text():
    assert isinstance(DeadlineExceeded(5), urllib.error.URLError)
    assert isinstance(ResponseTooLarge(10), urllib.error.URLError)
    assert "5 seconds" in str(DeadlineExceeded(5))
    assert "10 bytes" in str(ResponseTooLarge(10))


def test_http_error_body_is_capped_and_still_readable(server):
    server.mode, server.status = "big", 500
    with pytest.raises(urllib.error.HTTPError) as info:
        fetch(req(server), max_bytes=1_048_576, total_timeout=5)
    assert info.value.code == 500
    assert len(info.value.read()) == MAX_ERROR_BODY_BYTES


def test_small_http_error_body_is_preserved(server):
    server.mode, server.status, server.payload = "ok", 404, b'{"message": "Not Found"}'
    with pytest.raises(urllib.error.HTTPError) as info:
        fetch(req(server), max_bytes=1024, total_timeout=5)
    assert info.value.code == 404 and info.value.read() == b'{"message": "Not Found"}'


def test_http_error_with_a_dripping_body_hits_the_deadline(server):
    server.mode, server.status = "drip", 429
    t0 = time.monotonic()
    with pytest.raises(DeadlineExceeded):
        fetch(req(server), max_bytes=1024, total_timeout=0.6, op_timeout=5)
    assert time.monotonic() - t0 < 2.5


def test_truncated_body_is_reported(server):
    server.mode = "trunc"
    with pytest.raises(urllib.error.URLError) as info:
        fetch(req(server), max_bytes=1024, total_timeout=5)
    assert "truncated" in str(info.value)


def test_connection_refused_is_a_urlerror():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(urllib.error.URLError):
        fetch(urllib.request.Request("http://127.0.0.1:%d/" % port), max_bytes=1024, total_timeout=5)


def test_other_exceptions_propagate_unchanged():
    with patch("urllib.request.urlopen", side_effect=ValueError("boom")):
        with pytest.raises(ValueError):
            fetch(urllib.request.Request("http://x/"), max_bytes=1024, total_timeout=5)


def _fake_response(payload: bytes):
    m = MagicMock()
    m.read.return_value = payload
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


def test_stand_in_responses_without_a_real_read1_still_work():
    with patch("urllib.request.urlopen", return_value=_fake_response(b"hello")):
        assert fetch(urllib.request.Request("http://x/"), max_bytes=1024, total_timeout=5) == b"hello"
    with patch("urllib.request.urlopen", return_value=_fake_response(b"z" * 2000)):
        with pytest.raises(ResponseTooLarge):
            fetch(urllib.request.Request("http://x/"), max_bytes=1024, total_timeout=5)


def test_urlopen_gets_the_per_operation_timeout():
    with patch("urllib.request.urlopen", return_value=_fake_response(b"{}")) as m:
        fetch(urllib.request.Request("http://x/"), max_bytes=1024, total_timeout=5, op_timeout=7)
    assert m.call_args.kwargs["timeout"] == 7


@pytest.mark.parametrize("mb,tt", [(1023, 5), (100_000_001, 5), (True, 5), ("a", 5), (1024.5, 5),
                                   (2048, 0), (2048, -1), (2048, 3601), (2048, True), (2048, "x")])
def test_validate_limits_rejects_bad_values(mb, tt):
    with pytest.raises(ValueError):
        validate_limits(mb, tt)


@pytest.mark.parametrize("mb,tt", [(1024, 0.001), (100_000_000, 3600), (2048, 20), (2048, 20.5)])
def test_validate_limits_accepts_the_edges(mb, tt):
    validate_limits(mb, tt)
