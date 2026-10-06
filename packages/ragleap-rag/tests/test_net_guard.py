"""Attack-case tests for ragleap._net, ragleap.web and ingest_url(). A loopback
HTTP server stands in for the network; `pretend_public` makes names ending in
.test resolve to it while still passing the public-address check, so redirect
re-validation and IP pinning are exercised for real."""
import gzip
import http.server
import threading
import time
import zlib

import pytest

from ragleap import _net
from ragleap._net import UnsafeURLError, fetch_public

MARKER = "ragleapmarker"
PAGE = ("<html><body><article>" + f"<p>Paragraph with {MARKER} and enough ordinary words to resemble real article content.</p>" * 30 + "</article></body></html>").encode()


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", headers=None, length=True):
        self.server.hosts.append(self.headers.get("Host"))
        try:
            self.send_response(status)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            if length:
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        port = self.server.server_address[1]
        if self.path == "/redirect-private":
            self._send(302, headers={"Location": f"http://127.0.0.1:{port}/"})
        elif self.path == "/loop":
            self._send(302, headers={"Location": "/loop"})
        elif self.path == "/big":
            self._send(200, b"x" * 5000)
        elif self.path == "/big-no-length":
            self._send(200, b"x" * 5000, length=False)
        elif self.path == "/missing":
            self._send(404, b"nope")
        elif self.path == "/br":
            self._send(200, b"x", headers={"Content-Encoding": "br"})
        elif self.path == "/gzip-bad":
            self._send(200, b"not gzip data", headers={"Content-Encoding": "gzip"})
        elif self.path == "/gzip-truncated":
            self._send(200, gzip.compress(PAGE)[:-20], headers={"Content-Encoding": "gzip"})
        elif self.path == "/gzip-ok":
            self._send(200, gzip.compress(PAGE), headers={"Content-Encoding": "gzip"})
        elif self.path == "/deflate-ok":
            self._send(200, zlib.compress(PAGE), headers={"Content-Encoding": "deflate"})
        elif self.path == "/gzip-bomb":
            self._send(200, gzip.compress(bytes(20_000_000)), headers={"Content-Encoding": "gzip"})
        elif self.path == "/slow":
            time.sleep(3)
            self._send(200, PAGE)
        else:
            self._send(200, PAGE)


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.hosts = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def pretend_public(monkeypatch):
    real = _net._resolve

    def fake(host, port, allow_private):
        return "127.0.0.1" if host.endswith(".test") else real(host, port, allow_private)

    monkeypatch.setattr(_net, "_resolve", fake)


def url(server, path="/", host="127.0.0.1"):
    return f"http://{host}:{server.server_address[1]}{path}"


@pytest.mark.parametrize("bad", [
    "http://127.0.0.1/", "http://localhost/", "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/",
    "http://192.168.1.1/", "http://172.16.0.1/", "http://0.0.0.0/", "http://100.64.0.1/",
])
def test_non_public_targets_are_refused(bad):
    with pytest.raises(UnsafeURLError):
        fetch_public(bad)


@pytest.mark.parametrize("odd", [
    "http://2130706433/", "http://0x7f.0.0.1/", "http://[::ffff:127.0.0.1]/", "http://[fd00::1]/",
])
def test_odd_address_forms_are_refused_or_unresolvable(odd):
    with pytest.raises((UnsafeURLError, OSError)):
        fetch_public(odd)


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/",
    "javascript:alert(1)", "//example.com/x", "http://user:pass@example.com/", "http:///nohost",
])
def test_bad_schemes_credentials_and_missing_host_are_refused(bad):
    with pytest.raises(UnsafeURLError):
        fetch_public(bad)


def test_allow_private_fetches_loopback(server):
    assert MARKER.encode() in fetch_public(url(server), allow_private=True)


def test_connects_to_validated_ip_and_sends_original_host(server, pretend_public):
    assert MARKER.encode() in fetch_public(url(server, host="pinned.test"))
    assert server.hosts == [f"pinned.test:{server.server_address[1]}"]


def test_redirect_to_private_address_is_refused(server, pretend_public):
    with pytest.raises(UnsafeURLError):
        fetch_public(url(server, "/redirect-private", host="pinned.test"))


def test_redirect_loop_returns_none(server, pretend_public):
    assert fetch_public(url(server, "/loop", host="pinned.test")) is None


@pytest.mark.parametrize("path", ["/big", "/big-no-length"])
def test_oversized_body_returns_none(server, pretend_public, path):
    assert fetch_public(url(server, path, host="pinned.test"), max_bytes=1000) is None


@pytest.mark.parametrize("path", ["/missing", "/br", "/gzip-bad", "/gzip-truncated"])
def test_non_200_and_encoded_responses_return_none(server, pretend_public, path):
    assert fetch_public(url(server, path, host="pinned.test")) is None


def test_slow_server_hits_the_timeout(server, pretend_public):
    started = time.monotonic()
    with pytest.raises(OSError):
        fetch_public(url(server, "/slow", host="pinned.test"), timeout=1)
    assert time.monotonic() - started < 2.5


def test_fetch_url_text_refuses_loopback_by_default(server):
    pytest.importorskip("trafilatura")
    from ragleap.web import fetch_url_text
    with pytest.raises(UnsafeURLError):
        fetch_url_text(url(server))


def test_fetch_url_text_extracts_when_private_is_allowed(server):
    pytest.importorskip("trafilatura")
    from ragleap.web import fetch_url_text
    assert MARKER in fetch_url_text(url(server), allow_private=True)


def test_ingest_url_refuses_loopback_by_default(rag, server):
    pytest.importorskip("trafilatura")
    with pytest.raises(ValueError):
        rag.ingest_url(url(server))


@pytest.mark.parametrize("path", ["/gzip-ok", "/deflate-ok"])
def test_compressed_responses_are_decoded(server, pretend_public, path):
    assert MARKER.encode() in fetch_public(url(server, path, host="pinned.test"))


def test_decompression_bomb_returns_none(server, pretend_public):
    assert fetch_public(url(server, "/gzip-bomb", host="pinned.test"), max_bytes=100_000) is None
