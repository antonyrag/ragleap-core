"""Tests for ragleap_integrations._net - URL validation, the public-address
check, and https_post() against a real local TLS server with a throwaway
certificate (so hostname verification, IP pinning and the wall-clock
deadline are exercised for real, not mocked). DNS and the TCP connect are
injected so no test needs the network or a public address."""
import os
import shutil
import socket
import ssl
import subprocess
import threading
import time

import pytest

from ragleap_integrations._net import (
    TransportError,
    https_post,
    resolve_public,
    validate_url,
)

PUBLIC_IP = "93.184.216.34"


# --------------------------------------------------------------------------
# validate_url
# --------------------------------------------------------------------------

def test_validate_url_ok():
    assert validate_url("https://Mcp.Example.com./mcp?x=1") == ("mcp.example.com", 443, "/mcp?x=1")
    assert validate_url("https://mcp.example.com") == ("mcp.example.com", 443, "/")
    assert validate_url("https://mcp.example.com:8443/a") == ("mcp.example.com", 8443, "/a")


@pytest.mark.parametrize(
    "url, code",
    [
        ("", "url_length"),
        (None, "url_length"),
        ("https://example.com/" + "a" * 2100, "url_length"),
        ("https://exa mple.com/", "url_chars"),
        ("https://example.com/\n", "url_chars"),
        ("http://example.com/mcp", "scheme"),
        ("ftp://example.com/", "scheme"),
        ("https://user:pw@example.com/", "creds"),
        ("https://user@example.com/", "creds"),
        ("https://127.0.0.1/mcp", "ip_literal"),
        ("https://[::1]/mcp", "ip_literal"),
        ("https:///mcp", "host"),
        ("https://ex\u00e4mple.com/", "host"),
        ("https://example.com:0/", "port"),
        ("https://example.com:99999/", "port"),
        ("https://example.com:abc/", "port"),
    ],
)
def test_validate_url_rejects(url, code):
    with pytest.raises(TransportError) as e:
        validate_url(url)
    assert e.value.code == code


def test_transport_error_message_comes_from_constant_table():
    assert TransportError("deadline").message == "response too slow"
    assert TransportError("nonsense").message == "request failed"


# --------------------------------------------------------------------------
# resolve_public
# --------------------------------------------------------------------------

def _resolver(*ips):
    def resolve(host, port, type=0):
        out = []
        for ip in ips:
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            out.append((fam, socket.SOCK_STREAM, 6, "", (ip, port)))
        return out
    return resolve


def test_resolve_public_returns_first_public_ip():
    assert resolve_public("h", 443, _resolver(PUBLIC_IP, "8.8.8.8")) == PUBLIC_IP
    assert resolve_public("h", 443, _resolver("2606:4700:4700::1111")) == "2606:4700:4700::1111"


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",          # loopback
        "10.1.2.3",           # private
        "172.16.0.5",         # private
        "192.168.1.1",        # private
        "169.254.169.254",    # link-local / cloud metadata
        "100.64.0.1",         # carrier-grade NAT
        "0.0.0.0",            # unspecified
        "224.0.0.1",          # multicast
        "::1",                # IPv6 loopback
        "fe80::1",            # IPv6 link-local
        "fc00::1",            # IPv6 unique local
        "::ffff:127.0.0.1",   # IPv4-mapped loopback
        "::ffff:10.0.0.1",    # IPv4-mapped private
        "::ffff:169.254.169.254",
    ],
)
def test_resolve_public_refuses_non_public(ip):
    with pytest.raises(TransportError) as e:
        resolve_public("h", 443, _resolver(ip))
    assert e.value.code == "non_public"


def test_resolve_public_refuses_when_any_address_is_private():
    with pytest.raises(TransportError) as e:
        resolve_public("h", 443, _resolver(PUBLIC_IP, "10.0.0.1"))
    assert e.value.code == "non_public"


def test_resolve_public_accepts_ipv4_mapped_public():
    assert resolve_public("h", 443, _resolver("::ffff:93.184.216.34")) == "::ffff:93.184.216.34"


def test_resolve_public_dns_failure_and_empty_answer():
    def boom(host, port, type=0):
        raise socket.gaierror("nope")
    with pytest.raises(TransportError) as e:
        resolve_public("h", 443, boom)
    assert e.value.code == "no_resolve"
    with pytest.raises(TransportError) as e:
        resolve_public("h", 443, lambda host, port, type=0: [])
    assert e.value.code == "no_resolve"


# --------------------------------------------------------------------------
# A real local TLS server
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def tls_material(tmp_path_factory):
    if shutil.which("openssl") is None:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("openssl is required for the TLS tests in CI")
        pytest.skip("openssl not installed")
    d = tmp_path_factory.mktemp("tls")
    cert, key = str(d / "cert.pem"), str(d / "key.pem")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
         "-nodes", "-keyout", key, "-out", cert, "-days", "2", "-subj", "/CN=mcp.example.com",
         "-addext", "subjectAltName=DNS:mcp.example.com"],
        check=True, capture_output=True,
    )
    return cert, key


def read_request(conn):
    """Reads one HTTP request; returns (head_bytes, body_bytes)."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            return data, b""
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n")[1:]:
        k, _, v = line.partition(b":")
        if k.strip().lower() == b"content-length":
            length = int(v.strip())
    while len(rest) < length:
        chunk = conn.recv(4096)
        if not chunk:
            break
        rest += chunk
    return head, rest


class Server:
    def __init__(self, handler, tls_material, use_tls=True):
        self.handler = handler
        self.requests = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.use_tls = use_tls
        self.ctx = None
        if use_tls:
            self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ctx.load_cert_chain(*tls_material)
        self._closed = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self._closed:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            if self.use_tls:
                conn = self.ctx.wrap_socket(conn, server_side=True)
            self.handler(self, conn)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def close(self):
        self._closed = True
        self.sock.close()


@pytest.fixture
def make_server(tls_material):
    servers = []

    def factory(handler, use_tls=True):
        s = Server(handler, tls_material, use_tls)
        servers.append(s)
        return s

    yield factory
    for s in servers:
        s.close()


class Client:
    """Injected DNS/connect/TLS so the tests run offline."""

    def __init__(self, server, tls_material):
        self.server = server
        self.connects = []
        cert, _ = tls_material
        self.ctx = ssl.create_default_context(cafile=cert)
        self.ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    def kwargs(self, **extra):
        def connect(ip, port, timeout):
            self.connects.append((ip, port))
            return socket.create_connection(("127.0.0.1", self.server.port), timeout=timeout)
        base = dict(resolver=_resolver(PUBLIC_IP), connect=connect, ssl_context=self.ctx)
        base.update(extra)
        return base


def respond(conn, status=200, body=b"", ctype="application/json", extra=""):
    head = (f"HTTP/1.1 {status} X\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
            f"{extra}Connection: close\r\n\r\n").encode()
    conn.sendall(head + body)


def ok_handler(server, conn):
    head, body = read_request(conn)
    server.requests.append((head, body))
    respond(conn, 200, b'{"ok": true}')


URL = "https://mcp.example.com/mcp"


def test_post_roundtrip_pins_ip_and_sends_expected_request(make_server, tls_material):
    srv = make_server(ok_handler)
    cl = Client(srv, tls_material)
    resp = https_post(URL, {"Content-Type": "application/json", "X-Test": "1"}, b'{"a": 1}', **cl.kwargs())
    assert resp.status == 200
    assert resp.body == b'{"ok": true}'
    assert resp.content_type == "application/json"
    assert resp.headers["content-length"] == "12"
    # connected to the resolved IP and the URL's port, never to the hostname
    assert cl.connects == [(PUBLIC_IP, 443)]
    head, body = srv.requests[0]
    lines = head.decode().split("\r\n")
    assert lines[0] == "POST /mcp HTTP/1.1"
    h = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in lines[1:]}
    assert h["host"] == "mcp.example.com"
    assert h["accept-encoding"] == "identity"
    assert h["connection"] == "close"
    assert h["x-test"] == "1"
    assert h["content-length"] == "8"
    assert body == b'{"a": 1}'


def test_explicit_port_is_used_for_connect_and_host_header(make_server, tls_material):
    srv = make_server(ok_handler)
    cl = Client(srv, tls_material)
    https_post("https://mcp.example.com:8443/x", {}, b"{}", **cl.kwargs())
    assert cl.connects == [(PUBLIC_IP, 8443)]
    assert b"Host: mcp.example.com:8443" in srv.requests[0][0]


def test_non_public_address_is_refused_before_any_connect(make_server, tls_material):
    srv = make_server(ok_handler)
    cl = Client(srv, tls_material)
    with pytest.raises(TransportError) as e:
        https_post(URL, {}, b"{}", **cl.kwargs(resolver=_resolver("10.0.0.5")))
    assert e.value.code == "non_public"
    assert cl.connects == []


def test_hostname_mismatch_fails_tls_verification(make_server, tls_material):
    srv = make_server(ok_handler)
    cl = Client(srv, tls_material)
    with pytest.raises(TransportError) as e:
        https_post("https://other.example.com/mcp", {}, b"{}", **cl.kwargs())
    assert e.value.code == "tls"


def test_redirect_is_returned_not_followed(make_server, tls_material):
    def handler(server, conn):
        read_request(conn)
        respond(conn, 302, b"", extra="Location: https://evil.example.net/\r\n")
    cl = Client(make_server(handler), tls_material)
    resp = https_post(URL, {}, b"{}", **cl.kwargs())
    assert resp.status == 302
    assert resp.headers["location"] == "https://evil.example.net/"
    assert len(cl.connects) == 1


def test_error_status_body_is_returned(make_server, tls_material):
    def handler(server, conn):
        read_request(conn)
        respond(conn, 400, b'{"jsonrpc":"2.0","id":null,"error":{"code":-32020,"message":"m"}}')
    cl = Client(make_server(handler), tls_material)
    resp = https_post(URL, {}, b"{}", **cl.kwargs())
    assert resp.status == 400
    assert b"-32020" in resp.body


def test_response_larger_than_cap_is_refused(make_server, tls_material):
    def handler(server, conn):
        read_request(conn)
        respond(conn, 200, b"x" * 20000)
    cl = Client(make_server(handler), tls_material)
    with pytest.raises(TransportError) as e:
        https_post(URL, {}, b"{}", **cl.kwargs(max_bytes=1000))
    assert e.value.code == "too_large"


def test_truncated_body_is_an_error_not_a_short_success(make_server, tls_material):
    def handler(server, conn):
        read_request(conn)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n" + b"x" * 10)
    cl = Client(make_server(handler), tls_material)
    with pytest.raises(TransportError) as e:
        https_post(URL, {}, b"{}", **cl.kwargs())
    assert e.value.code == "io"


def test_chunked_response_is_decoded(make_server, tls_material):
    def handler(server, conn):
        read_request(conn)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
                     b"5\r\n{\"a\":\r\n3\r\n 1}\r\n0\r\n\r\n")
    cl = Client(make_server(handler), tls_material)
    resp = https_post(URL, {}, b"{}", **cl.kwargs())
    assert resp.body == b'{"a": 1}'


def test_event_stream_stops_early_when_the_caller_says_so(make_server, tls_material):
    def handler(server, conn):
        read_request(conn)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
        conn.sendall(b'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n')
        time.sleep(8)  # a server that never closes the stream
    cl = Client(make_server(handler), tls_material)
    t0 = time.monotonic()
    resp = https_post(URL, {}, b"{}", **cl.kwargs(stop=lambda buf: b'"id":1' in buf))
    assert time.monotonic() - t0 < 4
    assert resp.content_type == "text/event-stream"
    assert b'"id":1' in resp.body


# --- the wall-clock deadline ------------------------------------------------

def test_slow_drip_body_hits_the_deadline_not_the_per_operation_timeout(make_server, tls_material):
    """One byte every 0.1 s never trips the 5 s per-operation timeout; only
    the wall-clock deadline can stop it. A check between chunks alone would
    block here for far longer than the deadline."""
    def handler(server, conn):
        read_request(conn)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 100000\r\n\r\n")
        for _ in range(200):
            conn.sendall(b"x")
            time.sleep(0.1)
    cl = Client(make_server(handler), tls_material)
    t0 = time.monotonic()
    with pytest.raises(TransportError) as e:
        https_post(URL, {}, b"{}", **cl.kwargs(total_timeout=1.0, op_timeout=5.0))
    assert e.value.code == "deadline"
    assert time.monotonic() - t0 < 4


def test_slow_drip_headers_hit_the_deadline(make_server, tls_material):
    def handler(server, conn):
        read_request(conn)
        for b in b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nX-Slow: yes\r\n":
            conn.sendall(bytes([b]))
            time.sleep(0.1)
        time.sleep(10)
    cl = Client(make_server(handler), tls_material)
    t0 = time.monotonic()
    with pytest.raises(TransportError) as e:
        https_post(URL, {}, b"{}", **cl.kwargs(total_timeout=1.0, op_timeout=5.0))
    assert e.value.code == "deadline"
    assert time.monotonic() - t0 < 4


def test_stalled_tls_handshake_hits_the_deadline(make_server, tls_material):
    def handler(server, conn):
        time.sleep(10)  # accepts TCP, never speaks TLS
    cl = Client(make_server(handler, use_tls=False), tls_material)
    t0 = time.monotonic()
    with pytest.raises(TransportError) as e:
        https_post(URL, {}, b"{}", **cl.kwargs(total_timeout=1.0, op_timeout=5.0))
    assert e.value.code == "deadline"
    assert time.monotonic() - t0 < 4


def test_connect_failure_is_a_constant_error(tls_material):
    def refuse(ip, port, timeout):
        raise ConnectionRefusedError("secret library text")
    ctx = ssl.create_default_context(cafile=tls_material[0])
    with pytest.raises(TransportError) as e:
        https_post(URL, {}, b"{}", resolver=_resolver(PUBLIC_IP), connect=refuse, ssl_context=ctx)
    assert e.value.code == "connect"
    assert "secret" not in e.value.message
