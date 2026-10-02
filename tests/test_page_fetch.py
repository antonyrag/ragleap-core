"""
Tests for core/page_fetch.py and the fetch_page action tool. No real network:
DNS, sockets and TLS are faked. Covers allowlist matching, SSRF defences,
redirect handling, caps, HTML-to-text, planner validation and gate paths.
"""
import io

import pytest

from core import page_fetch as pf
from core.employees import actions
from core.employees._db import get_connection


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("BROWSER_FETCH_ENABLED", "true")
    monkeypatch.setenv("BROWSER_ALLOWED_DOMAINS",
                       "docs.example.com, *.wiki.example.org, com, *.org, localhost, *.com")


# ---- config / allowlist ----

def test_allowlist_parsing_drops_tlds_and_bare_names():
    assert pf.allowed_domains() == ["docs.example.com", "*.wiki.example.org"]


def test_host_allowed_matrix():
    assert pf.host_allowed("docs.example.com")
    assert pf.host_allowed("a.wiki.example.org") and pf.host_allowed("a.b.wiki.example.org")
    for h in ("wiki.example.org", "evil.org", "docs.example.com.evil.net", "xdocs.example.com",
              "example.com", "localhost", ""):
        assert not pf.host_allowed(h), h


def test_enabled_needs_flag_and_domains(monkeypatch):
    assert pf.enabled()
    monkeypatch.delenv("BROWSER_FETCH_ENABLED")
    assert not pf.enabled()
    monkeypatch.setenv("BROWSER_FETCH_ENABLED", "true")
    monkeypatch.setenv("BROWSER_ALLOWED_DOMAINS", "")
    assert not pf.enabled()


# ---- URL validation ----

@pytest.mark.parametrize("url", [
    "", "javascript:alert(1)", "ftp://docs.example.com/", "http://docs.example.com/",
    "https://evil.example.net/", "https://docs.example.com.evil.net/",
    "https://wiki.example.org/", "https://docs.example.com:8443/",
    "https://user:pw@docs.example.com/", "https://127.0.0.1/", "https://[::1]/",
    "https://docs.example.com/a b", "https://docs.example.com/a\nb",
    "https://docs.example.com/" + "a" * 300, "https://d\u00f3cs.example.com/",
])
def test_validate_rejects(url):
    with pytest.raises(ValueError):
        pf.validate_url(url)


def test_validate_accepts_and_normalises():
    assert pf.validate_url("https://DOCS.example.com/Guide?q=1") == ("docs.example.com", "/Guide?q=1")
    assert pf.validate_url("https://a.wiki.example.org:443") == ("a.wiki.example.org", "/")


# ---- DNS / SSRF ----

def fake_dns(*ips):
    def f(host, port, type=0, **kw):
        return [(2, 1, 6, "", (ip, port)) for ip in ips]
    return f


def test_resolve_public_returns_first_ip(monkeypatch):
    monkeypatch.setattr(pf.socket, "getaddrinfo", fake_dns("93.184.216.34", "93.184.216.35"))
    assert pf.resolve_public("docs.example.com") == "93.184.216.34"


@pytest.mark.parametrize("bad", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1",
                                 "172.16.0.9", "100.64.0.1", "0.0.0.0", "::1", "fe80::1",
                                 "fc00::1", "::ffff:10.0.0.5"])
def test_resolve_refuses_non_public(monkeypatch, bad):
    monkeypatch.setattr(pf.socket, "getaddrinfo", fake_dns(bad))
    with pytest.raises(ValueError):
        pf.resolve_public("docs.example.com")


def test_resolve_refuses_if_any_address_is_private(monkeypatch):
    monkeypatch.setattr(pf.socket, "getaddrinfo", fake_dns("93.184.216.34", "10.0.0.5"))
    with pytest.raises(ValueError):
        pf.resolve_public("docs.example.com")
    monkeypatch.setattr(pf.socket, "getaddrinfo", fake_dns())
    with pytest.raises(ValueError):
        pf.resolve_public("docs.example.com")


# ---- _request: pinned IP, SNI, clean headers ----

class FakeSock:
    def __init__(self, raw=b""):
        self.raw, self.sent = raw, b""

    def sendall(self, data):
        self.sent += data

    def makefile(self, *a, **k):
        return io.BytesIO(self.raw)

    def settimeout(self, t):
        pass

    def close(self):
        pass


def _resp(body=b"<p>hello</p>", status="200 OK", extra=""):
    return (f"HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\n{extra}"
            f"Content-Length: {len(body)}\r\n\r\n").encode() + body


def _patch_net(monkeypatch, sock):
    seen = {}

    def cc(addr, timeout=None):
        seen["addr"] = addr
        return object()

    class Ctx:
        def wrap_socket(self, s, server_hostname=None):
            seen["sni"] = server_hostname
            return sock

    monkeypatch.setattr(pf.socket, "create_connection", cc)
    monkeypatch.setattr(pf.ssl, "create_default_context", lambda: Ctx())
    return seen


def test_request_connects_to_pinned_ip_with_sni_and_clean_headers(monkeypatch):
    sock = FakeSock(_resp())
    seen = _patch_net(monkeypatch, sock)
    status, loc, ctype, body = pf._request("docs.example.com", "93.184.216.34", "/x?y=1")
    assert seen["addr"] == ("93.184.216.34", 443) and seen["sni"] == "docs.example.com"
    assert (status, ctype, body) == (200, "text/html", b"<p>hello</p>")
    assert sock.sent.startswith(b"GET /x?y=1 HTTP/1.1\r\n")
    assert b"Host: docs.example.com" in sock.sent and b"Accept-Encoding: identity" in sock.sent
    assert b"Cookie" not in sock.sent and b"Authorization" not in sock.sent


def test_request_returns_redirect_location_without_body(monkeypatch):
    raw = b"HTTP/1.1 302 Found\r\nLocation: /elsewhere\r\nContent-Length: 0\r\n\r\n"
    _patch_net(monkeypatch, FakeSock(raw))
    assert pf._request("docs.example.com", "93.184.216.34", "/")[:2] == (302, "/elsewhere")


def test_request_enforces_size_cap(monkeypatch):
    monkeypatch.setattr(pf, "MAX_BYTES", 50)
    _patch_net(monkeypatch, FakeSock(_resp(b"y" * 200)))
    with pytest.raises(ValueError):
        pf._request("docs.example.com", "93.184.216.34", "/")


# ---- HTML to text ----

def test_html_to_text_visible_only():
    out = pf.html_to_text(
        "<html><head><title>t</title><style>x{}</style></head><body><h1>Title</h1>"
        "<p>Hello <b>world</b> &amp; all</p><script>steal()</script><div hidden>secret</div>"
        "<p style='display: none'>nope</p><span aria-hidden=\"true\">ghost</span>"
        "<ul><li>one</li><li>two</li></ul><p>Visible</p></body></html>")
    assert "Title" in out and "Hello world & all" in out and "Visible" in out and "one" in out
    for hidden in ("steal", "secret", "nope", "ghost", "x{}"):
        assert hidden not in out


# ---- fetch_page flow ----

@pytest.fixture
def net(monkeypatch):
    state = {"calls": [], "script": []}
    monkeypatch.setattr(pf, "resolve_public", lambda host: "93.184.216.34")

    def fake(host, ip, path):
        state["calls"].append((host, ip, path))
        r = state["script"].pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(pf, "_request", fake)
    return state


def test_happy_path_html(net):
    net["script"] = [(200, "", "text/html", b"<body><h1>Guide</h1><p>Hi there</p><script>x()</script></body>")]
    out = pf.fetch_page("https://docs.example.com/x")
    assert out.startswith("Page fetch: https://docs.example.com/x (HTTP 200)")
    assert "Guide" in out and "Hi there" in out and "x()" not in out
    assert net["calls"] == [("docs.example.com", "93.184.216.34", "/x")]


def test_json_and_plain_pass_through(net):
    net["script"] = [(200, "", "application/json", b'{"a": 1}')]
    assert '{"a": 1}' in pf.fetch_page("https://docs.example.com/api")


def test_redirect_within_allowlist_is_followed(net):
    net["script"] = [(301, "/new", "", b""), (200, "", "text/plain", b"done")]
    assert "done" in pf.fetch_page("https://docs.example.com/old")
    assert net["calls"][1][2] == "/new"


@pytest.mark.parametrize("target", ["https://evil.example.net/x", "http://docs.example.com/x",
                                    "https://127.0.0.1/x", "https://docs.example.com:8443/x"])
def test_redirect_to_forbidden_target_is_refused(net, target):
    net["script"] = [(302, target, "", b"")]
    out = pf.fetch_page("https://docs.example.com/x")
    assert "refused" in out and len(net["calls"]) == 1


def test_too_many_redirects(net):
    net["script"] = [(302, "/a", "", b"")] * 4
    assert "too many redirects" in pf.fetch_page("https://docs.example.com/x")
    assert len(net["calls"]) == 4


def test_private_resolution_is_refused_before_connecting(net, monkeypatch):
    def private(host):
        raise pf._Refused("non_public")
    monkeypatch.setattr(pf, "resolve_public", private)
    assert "refused" in pf.fetch_page("https://docs.example.com/x") and net["calls"] == []


def test_disabled_or_bad_url_makes_no_request(net, monkeypatch):
    assert "refused" in pf.fetch_page("https://evil.example.net/")
    monkeypatch.delenv("BROWSER_FETCH_ENABLED")
    assert "refused" in pf.fetch_page("https://docs.example.com/")
    assert net["calls"] == []


def test_status_content_type_size_and_network_errors(net):
    net["script"] = [(404, "", "text/html", b"")]
    assert "HTTP 404" in pf.fetch_page("https://docs.example.com/x")
    net["script"] = [(200, "", "application/octet-stream", b"x")]
    assert "refused" in pf.fetch_page("https://docs.example.com/x")
    net["script"] = [pf._Refused("too_large")]
    assert "too large" in pf.fetch_page("https://docs.example.com/x")
    net["script"] = [ConnectionError("down")]
    assert "failed" in pf.fetch_page("https://docs.example.com/x")


def test_result_is_truncated(net):
    net["script"] = [(200, "", "text/plain", b"x" * 10000)]
    assert len(pf.fetch_page("https://docs.example.com/x")) <= pf.MAX_RESULT_CHARS


# ---- planner ----

def test_fetch_page_listed_only_when_enabled(monkeypatch):
    t = actions.available_tools()
    assert "fetch_page" in t
    listed = t["fetch_page"].split("one of: ")[1].split(". ")[0].split(", ")
    assert listed == ["docs.example.com", "*.wiki.example.org"]
    monkeypatch.delenv("BROWSER_FETCH_ENABLED")
    assert "fetch_page" not in actions.available_tools()
    monkeypatch.setenv("BROWSER_FETCH_ENABLED", "true")
    monkeypatch.delenv("BROWSER_ALLOWED_DOMAINS")
    assert "fetch_page" not in actions.available_tools()


def test_validate_plan_fetch_page():
    tools = {"fetch_page": "..."}
    ok = actions._validate_plan({"tool": "fetch_page", "target": "https://docs.example.com/a",
                                 "content": "checking the docs"}, tools)
    assert ok["channel"] == "fetch" and ok["target"] == "https://docs.example.com/a"
    for bad in ("https://evil.example.net/a", "http://docs.example.com/a", "docs.example.com", ""):
        assert actions._validate_plan({"tool": "fetch_page", "target": bad, "content": "why"}, tools) is None
    assert actions._validate_plan({"tool": "fetch_page", "target": "https://docs.example.com/a",
                                   "content": ""}, tools) is None


# ---- gate: full / semi (+ YES reply) / sensitive ----

URL = "https://docs.example.com/a"


@pytest.fixture
def gate(monkeypatch):
    import core.autonomy as au
    import core.employees.sensitivity as sens
    state = {"mode": "full", "ran": [], "sensitive": False}
    monkeypatch.setattr(au, "get_autonomy_settings", lambda: {
        "mode": state["mode"], "channels": [], "actions": [],
        "approval_channel": "telegram", "approval_target": "+10000000000"})
    monkeypatch.setattr(pf, "fetch_page", lambda url: (state["ran"].append(url) or "Page fetch: ok"))
    monkeypatch.setattr(au, "log_autonomous_action", lambda *a, **k: None)
    monkeypatch.setattr(au, "request_approval", lambda *a, **k: True)
    monkeypatch.setattr(au.employee_learning, "learn_from_owner_approval", lambda *a, **k: None)
    monkeypatch.setattr(sens, "is_sensitive_role", lambda r: state["sensitive"])
    yield state
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM autonomy_pending WHERE channel = 'fetch'")
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _plan(role=None):
    from core.employees.actions import run_action
    return run_action({"tool": "fetch_page", "channel": "fetch", "target": URL,
                       "content": "checking the docs", "subject": ""}, role=role)


def test_send_via_channel_fetch_dispatches(gate):
    from core.autonomy import _send_via_channel
    assert _send_via_channel("fetch", URL, "why") == "Page fetch: ok" and gate["ran"] == [URL]


def test_full_mode_fetches_immediately(gate):
    assert _plan()["status"] == "executed" and gate["ran"] == [URL]


def test_semi_mode_pends_then_yes_fetches(gate):
    import core.autonomy as au
    gate["mode"] = "semi"
    assert _plan()["status"] == "pending_approval" and gate["ran"] == []
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT action_id, target FROM autonomy_pending WHERE channel = 'fetch' "
                    "ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert row is not None and row[1] == URL
    assert "approved and executed" in au.process_approval_response(f"YES {row[0]}")
    assert gate["ran"] == [URL]


def test_sensitive_role_forced_to_semi(gate):
    gate["sensitive"] = True
    assert _plan(role="legal-helper")["status"] == "pending_approval" and gate["ran"] == []


# ---- no exception text leaks into results; TLS floor ----

def test_library_error_text_never_reaches_the_result(net):
    net["script"] = [ValueError("secret internals /srv/app/core.py line 42")]
    out = pf.fetch_page("https://docs.example.com/x")
    assert out == "Page fetch: failed; see server logs."
    net["script"] = [OSError("[SSL: CERTIFICATE_VERIFY_FAILED] (_ssl.c:1007)")]
    assert "SSL" not in pf.fetch_page("https://docs.example.com/x")


def test_every_refusal_code_has_constant_wording():
    for code, text in pf._REASONS.items():
        assert pf.fetch_page.__module__ and isinstance(text, str) and text
    assert pf._Refused("allowlist").code == "allowlist"


def test_request_requires_tls_1_2_or_newer(monkeypatch):
    import ssl
    holder = {}

    class Ctx:
        def wrap_socket(self, s, server_hostname=None):
            holder["ctx"] = self
            return FakeSock(_resp())

    monkeypatch.setattr(pf.socket, "create_connection", lambda addr, timeout=None: object())
    monkeypatch.setattr(pf.ssl, "create_default_context", lambda: Ctx())
    pf._request("docs.example.com", "93.184.216.34", "/")
    assert holder["ctx"].minimum_version == ssl.TLSVersion.TLSv1_2
