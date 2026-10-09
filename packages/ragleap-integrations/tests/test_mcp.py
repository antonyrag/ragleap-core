"""Tests for ragleap_integrations.mcp - configuration, header encoding,
x-mcp-header handling, the modern (2026-07-28) and legacy (2025-06-18)
request flows, the backward-compatibility detection, discovery, and
make_mcp_tools(). A recording fake transport replaces the network, so tests
assert on the exact URL, headers and JSON body each request carries, and on
the rule that rejected input never reaches the transport and that no
server-supplied text appears in a result's error."""
import base64
import json

import pytest

from ragleap_integrations import mcp
from ragleap_integrations._net import HttpResponse, TransportError
from ragleap_integrations.mcp import (
    META_CAPS,
    META_INFO,
    META_VERSION,
    McpClient,
    McpConfig,
    McpConfigError,
    McpDiscoveryError,
    McpServerConfig,
    McpToolSpec,
    _encode_header_value,
    _header_params,
    _header_values,
    _BadSchema,
    _Failure,
    make_mcp_tools,
)

URL = "https://mcp.example.com/mcp"
SECRET = "example-server-secret"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

class Call:
    def __init__(self, url, headers, raw, stop):
        self.url, self.headers, self.raw, self.stop = url, dict(headers), raw, stop
        self.body = json.loads(raw)

    @property
    def method(self):
        return self.body.get("method")


class Fake:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, url, headers, body, stop=None):
        call = Call(url, headers, body, stop)
        self.calls.append(call)
        return self.handler(call)

    @property
    def methods(self):
        return [c.method for c in self.calls]


def raw(status, body=b"", ctype="", headers=None):
    return HttpResponse(status, {k.lower(): v for k, v in (headers or {}).items()}, body, ctype)


def jresp(obj, status=200, headers=None):
    return raw(status, json.dumps(obj).encode(), "application/json", headers)


def ok(call, result, headers=None):
    return jresp({"jsonrpc": "2.0", "id": call.body["id"], "result": result}, headers=headers)


def rpc_err(call, code, message=SECRET, data=None, status=200):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return jresp({"jsonrpc": "2.0", "id": call.body.get("id"), "error": err}, status=status)


def sse(objs, status=200):
    body = "".join("data: " + json.dumps(o) + "\n\n" for o in objs).encode()
    return raw(status, body, "text/event-stream")


TEXT = {"content": [{"type": "text", "text": "found it"}]}
SCHEMA = {
    "type": "object",
    "properties": {
        "region": {"type": "string", "x-mcp-header": "Region"},
        "opts": {"type": "object", "properties": {"dry": {"type": "boolean", "x-mcp-header": "Dry-Run"}}},
        "limit": {"type": "integer", "x-mcp-header": "Limit"},
        "q": {"type": "string"},
    },
}


def modern(tools=None, call_result=None):
    def handler(call):
        if call.method == "tools/list":
            return ok(call, {"tools": tools or []})
        if call.method == "tools/call":
            return ok(call, call_result if call_result is not None else TEXT)
        raise AssertionError(call.method)
    return handler


def legacy(version="2025-06-18", session="sess-1", result=None, tools=None):
    """A server that only speaks the legacy handshake."""
    def handler(call):
        if call.headers.get("MCP-Protocol-Version") == mcp.MODERN_VERSION:
            return raw(400, b"")
        if call.method == "initialize":
            return ok(call, {"protocolVersion": version}, headers={"Mcp-Session-Id": session} if session else None)
        if call.method == "notifications/initialized":
            return raw(202)
        if call.method == "tools/list":
            return ok(call, {"tools": tools or []})
        if call.method == "tools/call":
            return ok(call, result if result is not None else {"content": [{"type": "text", "text": "legacy ok"}]})
        raise AssertionError(call.method)
    return handler


def cfg(**kw):
    servers = kw.pop("servers", [McpServerConfig("demo", URL, "s3cret")])
    allowed = kw.pop("allowed_tools", ["demo.lookup"])
    return McpConfig(servers=servers, allowed_tools=allowed, **kw)


def make(handler, **kw):
    fake = Fake(handler)
    return McpClient(cfg(**kw), transport=fake), fake


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

def test_valid_config_dedupes_allowlist_keeping_order():
    c = cfg(allowed_tools=["demo.b", "demo.a", "demo.b"])
    assert c.allowed_tools == ["demo.b", "demo.a"]


@pytest.mark.parametrize("name", ["", "a.b", "has space", "x" * 33, "caf\u00e9"])
def test_bad_server_names_rejected(name):
    with pytest.raises(McpConfigError):
        McpServerConfig(name, URL)


@pytest.mark.parametrize("url", ["http://mcp.example.com/", "https://127.0.0.1/mcp", "https://user:pw@mcp.example.com/", ""])
def test_bad_server_urls_rejected(url):
    with pytest.raises(McpConfigError):
        McpServerConfig("demo", url)


@pytest.mark.parametrize("token", ["", "a\r\nX-Evil: 1", "tab\there", 123])
def test_bad_tokens_rejected(token):
    with pytest.raises(McpConfigError):
        McpServerConfig("demo", URL, token)


def test_duplicate_server_names_and_empty_lists_rejected():
    s = McpServerConfig("demo", URL)
    with pytest.raises(McpConfigError):
        McpConfig(servers=[s, McpServerConfig("demo", URL)], allowed_tools=["demo.a"])
    with pytest.raises(McpConfigError):
        McpConfig(servers=[], allowed_tools=["demo.a"])
    with pytest.raises(McpConfigError):
        McpConfig(servers=[s], allowed_tools=[])


@pytest.mark.parametrize("entry", ["nodot", "nope.tool", "demo.", ".tool", "demo." + "x" * 129, "demo.a\nb", 5])
def test_bad_allowlist_entries_rejected(entry):
    with pytest.raises(McpConfigError):
        McpConfig(servers=[McpServerConfig("demo", URL)], allowed_tools=[entry])


@pytest.mark.parametrize("attr", ["max_result_chars", "max_description_chars", "max_schema_chars",
                                  "total_timeout", "op_timeout", "max_response_bytes"])
@pytest.mark.parametrize("value", [0, -1, "10", None, True])
def test_bad_limits_rejected(attr, value):
    with pytest.raises(McpConfigError):
        cfg(**{attr: value})


# --------------------------------------------------------------------------
# header value encoding
# --------------------------------------------------------------------------

def test_plain_values_are_not_encoded():
    assert _encode_header_value("US-East-1") == "US-East-1"
    assert _encode_header_value("with spaces inside") == "with spaces inside"
    assert _encode_header_value("") == ""


@pytest.mark.parametrize(
    "value",
    ["Hello, \u4e16\u754c", " padded ", "line1\nline2", "tab\there", "x\x7f", "=?base64?literal?=", "trail "],
)
def test_unsafe_values_use_the_base64_sentinel(value):
    out = _encode_header_value(value)
    assert out.startswith("=?base64?") and out.endswith("?=")
    assert base64.b64decode(out[len("=?base64?"):-2]).decode("utf-8") == value
    assert all(0x20 <= ord(c) <= 0x7E for c in out)


def test_sentinel_wire_format():
    assert _encode_header_value(" padded ") == "=?base64?IHBhZGRlZCA=?="


# --------------------------------------------------------------------------
# x-mcp-header
# --------------------------------------------------------------------------

def test_header_params_found_in_order_including_nested():
    assert _header_params(SCHEMA) == [
        (("region",), "Region"),
        (("opts", "dry"), "Dry-Run"),
        (("limit",), "Limit"),
    ]


def test_schema_without_annotations_has_none():
    assert _header_params({"type": "object", "properties": {"q": {"type": "string"}}}) == []
    assert _header_params({"type": "object"}) == []


@pytest.mark.parametrize(
    "props",
    [
        {"x": {"type": "number", "x-mcp-header": "X"}},                       # number is not allowed
        {"x": {"x-mcp-header": "X"}},                                         # no type
        {"x": {"type": ["string", "null"], "x-mcp-header": "X"}},             # type list
        {"x": {"type": "string", "x-mcp-header": "A"}, "y": {"type": "string", "x-mcp-header": "a"}},  # duplicate
        {"x": {"type": "string", "x-mcp-header": "Bad Name"}},
        {"x": {"type": "string", "x-mcp-header": "A:B"}},
        {"x": {"type": "string", "x-mcp-header": ""}},
        {"x": {"type": "string", "x-mcp-header": 5}},
        {"x": {"type": "array", "items": {"type": "string", "x-mcp-header": "Tag"}}},     # not on the properties chain
        {"x": {"anyOf": [{"type": "string", "x-mcp-header": "V"}]}},
    ],
)
def test_invalid_annotations_reject_the_whole_schema(props):
    with pytest.raises(_BadSchema):
        _header_params({"type": "object", "properties": props})


def test_annotation_on_the_root_schema_is_rejected():
    with pytest.raises(_BadSchema):
        _header_params({"type": "object", "x-mcp-header": "Root", "properties": {}})


def test_header_values_extraction():
    hp = _header_params(SCHEMA)
    assert _header_values(hp, {"region": "US-East-1", "limit": 5, "opts": {"dry": True}, "q": "x"}) == {
        "Region": "US-East-1", "Limit": "5", "Dry-Run": "true"}
    assert _header_values(hp, {"opts": {"dry": False}}) == {"Dry-Run": "false"}
    assert _header_values(hp, {"region": None, "q": "only"}) == {}
    assert _header_values(hp, {}) == {}


@pytest.mark.parametrize("args", [{"limit": 2 ** 53}, {"limit": 1.5}, {"region": {"a": 1}}, {"region": ["a"]}])
def test_header_values_reject_unmirrorable_values(args):
    with pytest.raises(_Failure) as e:
        _header_values(_header_params(SCHEMA), args)
    assert e.value.code == "bad_arguments"


# --------------------------------------------------------------------------
# a modern call
# --------------------------------------------------------------------------

def test_modern_call_sends_the_exact_request():
    c, fake = make(modern())
    r = c.call_tool("demo", "lookup", {"q": "invoice 7"})
    assert r.success is True and r.result == {"text": "found it"}
    call = fake.calls[0]
    assert call.url == URL
    assert call.headers["Content-Type"] == "application/json"
    assert call.headers["Accept"] == "application/json, text/event-stream"
    assert call.headers["MCP-Protocol-Version"] == "2026-07-28"
    assert call.headers["Mcp-Method"] == "tools/call"
    assert call.headers["Mcp-Name"] == "lookup"
    assert call.headers["Authorization"] == "Bearer s3cret"
    b = call.body
    assert b["jsonrpc"] == "2.0" and b["method"] == "tools/call" and isinstance(b["id"], int)
    assert b["params"]["name"] == "lookup"
    assert b["params"]["arguments"] == {"q": "invoice 7"}
    meta = b["params"]["_meta"]
    assert meta[META_VERSION] == "2026-07-28"
    assert meta[META_INFO]["name"] == "ragleap-integrations"
    assert meta[META_CAPS] == {}
    assert "s3cret" not in call.raw.decode()
    assert fake.methods == ["tools/call"]


def test_no_authorization_header_without_a_token():
    c, fake = make(modern(), servers=[McpServerConfig("demo", URL)])
    c.call_tool("demo", "lookup", {})
    assert "Authorization" not in fake.calls[0].headers


def test_non_ascii_tool_name_goes_in_mcp_name_as_base64():
    name = "d\u00e9j\u00e0"
    c, fake = make(modern(), allowed_tools=["demo." + name])
    assert c.call_tool("demo", name, {}).success is True
    assert fake.calls[0].headers["Mcp-Name"] == "=?base64?" + base64.b64encode(name.encode()).decode() + "?="
    assert fake.calls[0].body["params"]["name"] == name


def test_x_mcp_header_parameters_are_mirrored_into_headers():
    c, fake = make(modern())
    c.call_tool("demo", "lookup", {"region": "US-East-1", "limit": 5, "opts": {"dry": True}}, parameters=SCHEMA)
    h = fake.calls[0].headers
    assert h["Mcp-Param-Region"] == "US-East-1"
    assert h["Mcp-Param-Limit"] == "5"
    assert h["Mcp-Param-Dry-Run"] == "true"


def test_header_mirroring_uses_the_base64_form_when_needed():
    c, fake = make(modern())
    c.call_tool("demo", "lookup", {"region": " spaced "}, parameters=SCHEMA)
    assert fake.calls[0].headers["Mcp-Param-Region"] == _encode_header_value(" spaced ")
    assert fake.calls[0].headers["Mcp-Param-Region"].startswith("=?base64?")


def test_no_arguments_means_an_empty_object():
    c, fake = make(modern())
    c.call_tool("demo", "lookup")
    assert fake.calls[0].body["params"]["arguments"] == {}


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------

def test_text_parts_are_joined_and_non_text_is_noted():
    res = {"content": [{"type": "text", "text": "a"}, {"type": "image", "data": "x", "mimeType": "image/png"},
                       {"type": "text", "text": "b"}, "junk"]}
    c, _ = make(modern(call_result=res))
    r = c.call_tool("demo", "lookup", {})
    assert r.success and r.result == {"text": "a\nb\n[2 non-text content item(s) omitted]"}


def test_long_results_are_truncated_with_a_marker():
    res = {"content": [{"type": "text", "text": "x" * 50}]}
    c, _ = make(modern(call_result=res), max_result_chars=10)
    assert c.call_tool("demo", "lookup", {}).result == {"text": "x" * 10 + "\n[truncated]"}


def test_is_error_becomes_a_failed_tool_result_with_the_tool_text():
    res = {"isError": True, "content": [{"type": "text", "text": "no such invoice"}]}
    c, _ = make(modern(call_result=res))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and r.error == "no such invoice"


def test_is_error_without_text_still_fails():
    c, _ = make(modern(call_result={"isError": True, "content": []}))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and r.error


def test_content_must_be_a_list():
    c, _ = make(modern(call_result={"content": "nope"}))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "unusable response" in r.error


def test_input_required_result_is_reported_as_unsupported():
    c, _ = make(modern(call_result={"inputRequests": {"q": {"method": "elicitation/create"}}}))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "client input" in r.error


def test_event_stream_response_with_a_notification_before_the_result():
    def handler(call):
        return sse([{"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info"}},
                    {"jsonrpc": "2.0", "id": call.body["id"], "result": TEXT}])
    c, _ = make(handler)
    assert c.call_tool("demo", "lookup", {}).result == {"text": "found it"}


def test_event_stream_with_crlf_line_endings():
    def handler(call):
        body = ("data: " + json.dumps({"jsonrpc": "2.0", "id": call.body["id"], "result": TEXT}) + "\r\n\r\n").encode()
        return raw(200, body, "text/event-stream")
    c, _ = make(handler)
    assert c.call_tool("demo", "lookup", {}).success is True


def test_event_stream_whose_last_event_has_no_blank_line_is_accepted_at_eof():
    def handler(call):
        body = ("data: " + json.dumps({"jsonrpc": "2.0", "id": call.body["id"], "result": TEXT})).encode()
        return raw(200, body, "text/event-stream")
    c, _ = make(handler)
    assert c.call_tool("demo", "lookup", {}).success is True


@pytest.mark.parametrize(
    "response",
    [
        lambda call: jresp({"jsonrpc": "2.0", "id": 999, "result": TEXT}),            # wrong id
        lambda call: raw(200, b"not json", "application/json"),
        lambda call: raw(200, b"<html>hi</html>", "text/html"),
        lambda call: raw(200, b"", "application/json"),
        lambda call: sse([{"jsonrpc": "2.0", "id": 999, "result": TEXT}]),
        lambda call: jresp({"jsonrpc": "2.0", "id": call.body["id"], "result": "not an object"}),
        lambda call: jresp([1, 2, 3]),
    ],
)
def test_unusable_responses_become_constant_failures(response):
    c, _ = make(response)
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "unusable response" in r.error


def test_event_stream_response_ids_must_match():
    stop_calls = []

    def handler(call):
        stop_calls.append(call.stop)
        return ok(call, TEXT)
    c, fake = make(handler)
    c.call_tool("demo", "lookup", {})
    stop = fake.calls[0].stop
    rid = fake.calls[0].body["id"]
    done = ("data: " + json.dumps({"jsonrpc": "2.0", "id": rid, "result": {}}) + "\n\n").encode()
    other = ("data: " + json.dumps({"jsonrpc": "2.0", "id": rid + 100, "result": {}}) + "\n\n").encode()
    assert stop(done) is True
    assert stop(other) is False
    assert stop(done[:-1]) is False  # event not terminated yet
    assert stop(b"") is False


def test_json_rpc_error_reports_the_code_but_never_the_server_text():
    c, _ = make(lambda call: rpc_err(call, -32602, SECRET))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False
    assert "code -32602" in r.error and SECRET not in r.error


def test_http_error_reports_the_status_but_never_the_body():
    c, _ = make(lambda call: raw(500, SECRET.encode(), "text/plain"))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False
    assert "HTTP 500" in r.error and SECRET not in r.error


# --------------------------------------------------------------------------
# refusals: nothing reaches the transport
# --------------------------------------------------------------------------

def test_tool_outside_the_allowlist_is_refused_without_a_request():
    c, fake = make(modern())
    r = c.call_tool("demo", "other", {})
    assert r.success is False and "not allowlisted" in r.error
    assert fake.calls == []


def test_unknown_server_is_refused_without_a_request():
    c, fake = make(modern())
    assert c.call_tool("nope", "lookup", {}).success is False
    assert fake.calls == []


@pytest.mark.parametrize("args", ["a string", [1, 2], 5, {"f": object()}, {"f": float("nan") and object()}])
def test_bad_arguments_are_refused_without_a_request(args):
    c, fake = make(modern())
    r = c.call_tool("demo", "lookup", args)
    assert r.success is False and "arguments" in r.error
    assert fake.calls == []


def test_unmirrorable_header_argument_is_refused_without_a_request():
    c, fake = make(modern())
    r = c.call_tool("demo", "lookup", {"limit": 1.5}, parameters=SCHEMA)
    assert r.success is False and "arguments" in r.error
    assert fake.calls == []


def test_transport_errors_become_constant_results():
    def handler(call):
        raise TransportError("deadline")
    c, _ = make(handler)
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "response too slow" in r.error


def test_unexpected_exceptions_never_escape_or_leak():
    def handler(call):
        raise RuntimeError(SECRET)
    c, _ = make(handler)
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and SECRET not in r.error


def test_default_transport_passes_the_configured_limits(monkeypatch):
    seen = {}

    def fake_post(url, headers, body, **kw):
        seen.update(kw, url=url)
        return ok(Call(url, headers, body, None), TEXT)
    monkeypatch.setattr(mcp._net, "https_post", fake_post)
    c = McpClient(cfg(total_timeout=7, op_timeout=3, max_response_bytes=1234))
    assert c.call_tool("demo", "lookup", {}).success is True
    assert seen["url"] == URL
    assert (seen["total_timeout"], seen["op_timeout"], seen["max_bytes"]) == (7, 3, 1234)
    assert callable(seen["stop"])


# --------------------------------------------------------------------------
# compatibility: telling a modern server from a legacy one
# --------------------------------------------------------------------------

def test_legacy_server_is_detected_from_a_400_with_no_json_rpc_body():
    c, fake = make(legacy())
    r = c.call_tool("demo", "lookup", {"q": "x"})
    assert r.success and r.result == {"text": "legacy ok"}
    assert fake.methods == ["tools/call", "initialize", "notifications/initialized", "tools/call"]


def test_legacy_requests_carry_the_session_and_negotiated_version():
    c, fake = make(legacy())
    c.call_tool("demo", "lookup", {"q": "x"})
    init, note, call = fake.calls[1], fake.calls[2], fake.calls[3]
    assert init.body["params"]["protocolVersion"] == "2025-06-18"
    assert init.body["params"]["capabilities"] == {}
    assert init.body["params"]["clientInfo"]["name"] == "ragleap-integrations"
    assert init.headers["Authorization"] == "Bearer s3cret"
    for later in (note, call):
        assert later.headers["MCP-Protocol-Version"] == "2025-06-18"
        assert later.headers["Mcp-Session-Id"] == "sess-1"
        assert later.headers["Authorization"] == "Bearer s3cret"
        assert "Mcp-Method" not in later.headers and "Mcp-Name" not in later.headers
    assert "_meta" not in call.body["params"]
    assert call.body["params"] == {"name": "lookup", "arguments": {"q": "x"}}


def test_legacy_without_a_session_header_still_works():
    c, fake = make(legacy(session=None))
    assert c.call_tool("demo", "lookup", {}).success is True
    assert "Mcp-Session-Id" not in fake.calls[3].headers


@pytest.mark.parametrize("status", [404, 405])
def test_404_or_405_without_json_rpc_also_means_legacy(status):
    def handler(call):
        if call.headers.get("MCP-Protocol-Version") == mcp.MODERN_VERSION:
            return raw(status, b"<html>no</html>", "text/html")
        return legacy()(call)
    c, fake = make(handler)
    assert c.call_tool("demo", "lookup", {}).success is True


def test_modern_json_rpc_errors_are_not_mistaken_for_a_legacy_server():
    for status, code in ((400, -32020), (404, -32601)):
        c, fake = make(lambda call, s=status, k=code: rpc_err(call, k, status=s))
        r = c.call_tool("demo", "lookup", {})
        assert r.success is False and f"code {code}" in r.error and SECRET not in r.error
        assert fake.methods == ["tools/call"]  # no initialize attempted


def test_server_that_is_neither_modern_nor_legacy_gets_a_clear_error():
    c, fake = make(lambda call: raw(404, b"<html>nope</html>", "text/html"))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "transport" in r.error
    assert fake.methods == ["tools/call", "initialize"]


def test_a_legacy_servers_own_json_rpc_rejection_means_legacy():
    """What a live DeepWiki server answered to the modern request: a 400 with
    its own JSON-RPC error (-32600), not a modern error. The spec says to fall
    back to initialize for anything that is not a recognized modern error."""
    def handler(call):
        if call.headers.get("MCP-Protocol-Version") == mcp.MODERN_VERSION:
            body = {"jsonrpc": "2.0", "id": "server-error",
                    "error": {"code": -32600, "message": "Bad Request: Unsupported protocol version: 2026-07-28"}}
            return jresp(body, status=400)
        return legacy()(call)
    c, fake = make(handler)
    r = c.call_tool("demo", "lookup", {"q": "x"})
    assert r.success and r.result == {"text": "legacy ok"}
    assert fake.methods == ["tools/call", "initialize", "notifications/initialized", "tools/call"]


@pytest.mark.parametrize("code", [-32600, -32602, -32000, -32601, -32603])
def test_a_400_with_any_non_modern_code_falls_back(code):
    def handler(call):
        if call.headers.get("MCP-Protocol-Version") == mcp.MODERN_VERSION:
            return rpc_err(call, code, status=400)
        return legacy()(call)
    c, fake = make(handler)
    assert c.call_tool("demo", "lookup", {}).success is True
    assert fake.methods[:2] == ["tools/call", "initialize"]


@pytest.mark.parametrize("code", [-32020, -32021])
def test_a_400_with_a_recognized_modern_code_is_reported_not_downgraded(code):
    c, fake = make(lambda call: rpc_err(call, code, status=400))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and f"code {code}" in r.error and SECRET not in r.error
    assert fake.methods == ["tools/call"]


def test_modern_server_rejecting_arguments_with_a_400_is_not_silently_downgraded():
    """Some servers answer invalid params with 400 and -32602, which the spec
    rule reads as legacy. The failed fallback must still show the first reply."""
    def handler(call):
        if call.headers.get("MCP-Protocol-Version") == mcp.MODERN_VERSION:
            return rpc_err(call, -32602, status=400)
        return raw(404, b"<html>no</html>", "text/html")
    c, fake = make(handler)
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "first reply code -32602" in r.error and SECRET not in r.error
    assert fake.methods == ["tools/call", "initialize"]
    assert c._eras == {}


def test_unsupported_version_code_without_a_usable_list_is_an_error():
    c, fake = make(lambda call: rpc_err(call, -32022, status=400))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "protocol version" in r.error
    assert fake.methods == ["tools/call"]


def test_unsupported_version_error_with_a_legacy_overlap_falls_back():
    def handler(call):
        if call.headers.get("MCP-Protocol-Version") == mcp.MODERN_VERSION:
            return rpc_err(call, -32022, status=400, data={"supported": ["2025-06-18"]})
        return legacy()(call)
    c, fake = make(handler)
    assert c.call_tool("demo", "lookup", {}).success is True
    assert fake.methods[:2] == ["tools/call", "initialize"]


def test_unsupported_version_error_without_overlap_is_an_error_and_no_handshake():
    c, fake = make(lambda call: rpc_err(call, -32022, status=400, data={"supported": ["2099-01-01"]}))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "protocol version" in r.error
    assert fake.methods == ["tools/call"]


def test_legacy_server_answering_with_a_version_we_do_not_support_is_refused():
    c, fake = make(legacy(version="2099-01-01"))
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "protocol version" in r.error
    assert fake.methods == ["tools/call", "initialize"]  # no notification, no tool call


def test_legacy_initialize_error_and_notification_failure():
    def init_error(call):
        if call.headers.get("MCP-Protocol-Version") == mcp.MODERN_VERSION:
            return raw(400, b"")
        return rpc_err(call, -32603)
    c, _ = make(init_error)
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "code -32603" in r.error and SECRET not in r.error

    def note_fails(call):
        if call.method == "notifications/initialized":
            return raw(500, SECRET.encode())
        return legacy()(call)
    c, fake = make(note_fails)
    r = c.call_tool("demo", "lookup", {})
    assert r.success is False and "HTTP 500" in r.error and SECRET not in r.error
    assert fake.methods[-1] == "notifications/initialized"


def test_era_is_remembered_after_a_success():
    c, fake = make(legacy())
    c.call_tool("demo", "lookup", {})
    fake.calls.clear()
    c.call_tool("demo", "lookup", {})
    assert fake.methods == ["initialize", "notifications/initialized", "tools/call"]  # no modern attempt

    c, fake = make(modern())
    c.call_tool("demo", "lookup", {})
    c.call_tool("demo", "lookup", {})
    assert fake.methods == ["tools/call", "tools/call"]


def test_a_failed_legacy_attempt_does_not_pin_the_server_to_legacy():
    state = {"legacy_ok": False}

    def handler(call):
        if call.headers.get("MCP-Protocol-Version") == mcp.MODERN_VERSION:
            return raw(400, b"")
        if not state["legacy_ok"]:
            return raw(500)
        return legacy()(call)
    c, fake = make(handler)
    assert c.call_tool("demo", "lookup", {}).success is False
    state["legacy_ok"] = True
    fake.calls.clear()
    assert c.call_tool("demo", "lookup", {}).success is True
    assert fake.methods[0] == "tools/call"  # the modern attempt was repeated


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def tool_def(name, **kw):
    d = {"name": name, "description": "does " + name, "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}}
    d.update(kw)
    return d


def test_discovery_request_shape_and_allowlist_filtering():
    tools = [tool_def("lookup"), tool_def("search"), tool_def("extra")]
    c, fake = make(modern(tools=tools), allowed_tools=["demo.lookup", "demo.search"])
    d = c.discover()
    assert [t.name for t in d.tools] == ["lookup", "search"]
    assert d.skipped == []
    call = fake.calls[0]
    assert call.headers["Mcp-Method"] == "tools/list"
    assert "Mcp-Name" not in call.headers
    assert call.headers["MCP-Protocol-Version"] == "2026-07-28"
    assert call.body["method"] == "tools/list"
    assert "cursor" not in call.body["params"]
    assert call.body["params"]["_meta"][META_VERSION] == "2026-07-28"
    assert d.tools[0].description == "does lookup" and d.tools[0].server == "demo"
    assert len(fake.calls) == 1  # everything wanted was on page one


def test_discovery_follows_next_cursor_and_stops_when_everything_is_found():
    pages = {None: {"tools": [tool_def("extra")], "nextCursor": "c2"},
             "c2": {"tools": [tool_def("lookup")], "nextCursor": "c3"},
             "c3": {"tools": [tool_def("never_fetched")]}}

    def handler(call):
        return ok(call, pages[call.body["params"].get("cursor")])
    c, fake = make(handler)
    d = c.discover()
    assert [t.name for t in d.tools] == ["lookup"]
    assert [c_.body["params"].get("cursor") for c_ in fake.calls] == [None, "c2"]


def test_discovery_page_loop_is_bounded():
    def handler(call):
        return ok(call, {"tools": [tool_def("extra")], "nextCursor": "again"})
    c, fake = make(handler)
    d = c.discover()
    assert len(fake.calls) == mcp.MAX_LIST_PAGES
    assert d.tools == [] and d.skipped == [("demo.lookup", "not offered by the server")]


def test_discovery_skips_unusable_tools_with_reasons():
    tools = [
        tool_def("a", inputSchema={"type": "string"}),
        tool_def("b", inputSchema={"type": "object", "properties": {"x": {"type": "number", "x-mcp-header": "X"}}}),
        tool_def("c", inputSchema={"type": "object", "properties": {"p": {"type": "string", "description": "y" * 500}}}),
    ]
    c, _ = make(modern(tools=tools), allowed_tools=["demo.a", "demo.b", "demo.c", "demo.gone"], max_schema_chars=200)
    d = c.discover()
    assert d.tools == []
    assert dict(d.skipped) == {
        "demo.a": "inputSchema is not an object schema",
        "demo.b": "invalid x-mcp-header annotation",
        "demo.c": "inputSchema is too large",
        "demo.gone": "not offered by the server",
    }


def test_discovery_caps_descriptions_and_defaults_missing_schemas():
    tools = [{"name": "lookup", "description": "d" * 100}, {"name": "search", "description": 42}]
    c, _ = make(modern(tools=tools), allowed_tools=["demo.lookup", "demo.search"], max_description_chars=10)
    d = {t.name: t for t in c.discover().tools}
    assert d["lookup"].description == "d" * 10
    assert d["search"].description == ""
    assert d["lookup"].parameters == {"type": "object", "properties": {}}


def test_discovery_failure_raises_a_constant_message():
    c, _ = make(lambda call: raw(500, SECRET.encode()))
    with pytest.raises(McpDiscoveryError) as e:
        c.discover()
    assert "HTTP 500" in str(e.value) and SECRET not in str(e.value)

    def boom(call):
        raise TransportError("tls")
    c, _ = make(boom)
    with pytest.raises(McpDiscoveryError) as e:
        c.discover()
    assert "tls failure" in str(e.value)


def test_discovery_with_a_malformed_tool_list_fails_cleanly():
    c, _ = make(lambda call: ok(call, {"tools": "nope"}))
    with pytest.raises(McpDiscoveryError):
        c.discover()


# --------------------------------------------------------------------------
# make_mcp_tools
# --------------------------------------------------------------------------

def test_discovered_tools_are_ragleap_tools_and_the_list_is_a_snapshot():
    c, fake = make(modern(tools=[tool_def("lookup", inputSchema=SCHEMA, description="finds things")]))
    tools = make_mcp_tools(c.config, client=c)
    assert len(tools) == 1
    t = tools[0]
    assert t.name == "demo__lookup" and t.description == "finds things" and t.parameters == SCHEMA
    assert t.to_openai_schema()["function"]["name"] == "demo__lookup"
    assert t.to_gemini_schema()["name"] == "demo__lookup"
    r = t.call(region="US-East-1", q="x")
    assert r.success and r.result == {"text": "found it"}
    t.call(q="again")
    assert fake.methods == ["tools/list", "tools/call", "tools/call"]  # listed once, never refreshed
    assert fake.calls[1].headers["Mcp-Param-Region"] == "US-East-1"  # mirrored via the discovered schema


def test_owner_supplied_specs_use_no_network_at_setup():
    c, fake = make(modern())
    spec = McpToolSpec("demo", "lookup", "Look things up", {"type": "object", "properties": {"q": {"type": "string"}}})
    tools = make_mcp_tools(c.config, specs=[spec], client=c)
    assert fake.calls == []
    assert tools[0].description == "Look things up"
    assert tools[0].call(q="x").success is True
    assert fake.methods == ["tools/call"]


def test_bad_owner_specs_are_configuration_errors():
    c, _ = make(modern())
    good = {"type": "object", "properties": {}}
    for spec in (
        McpToolSpec("demo", "other", "d", good),                                               # not allowlisted
        McpToolSpec("demo", "lookup", 5, good),                                                # description
        McpToolSpec("demo", "lookup", "d", {"type": "string"}),                                # not an object schema
        McpToolSpec("demo", "lookup", "d", {"type": "object", "properties": {"x": {"type": "number", "x-mcp-header": "X"}}}),
    ):
        with pytest.raises(McpConfigError):
            make_mcp_tools(c.config, specs=[spec], client=c)


def test_exposed_names_are_sanitized_truncated_and_collisions_are_errors():
    servers = [McpServerConfig("a", URL), McpServerConfig("a__b", URL), McpServerConfig("demo", URL)]
    c = McpConfig(servers=servers, allowed_tools=["a.b__c", "a__b.c", "demo.get.weather v2", "demo." + "t" * 100])
    good = {"type": "object", "properties": {}}
    specs = [McpToolSpec("demo", "get.weather v2", "d", good), McpToolSpec("demo", "t" * 100, "d", good)]
    names = [t.name for t in make_mcp_tools(c, specs=specs, client=McpClient(c, transport=Fake(modern())))]
    assert names[0] == "demo__get_weather_v2"
    assert len(names[1]) == 64 and names[1].startswith("demo__ttt")
    clash = [McpToolSpec("a", "b__c", "d", good), McpToolSpec("a__b", "c", "d", good)]
    with pytest.raises(McpConfigError):
        make_mcp_tools(c, specs=clash, client=McpClient(c, transport=Fake(modern())))


def test_tool_handlers_never_raise():
    def boom(call):
        raise RuntimeError(SECRET)
    c, _ = make(boom)
    spec = McpToolSpec("demo", "lookup", "d", {"type": "object", "properties": {}})
    tool = make_mcp_tools(c.config, specs=[spec], client=c)[0]
    r = tool.call(q="x")
    assert r.success is False and SECRET not in (r.error or "")


def test_a_model_chosen_argument_named_like_our_internals_is_just_an_argument():
    c, fake = make(modern())
    spec = McpToolSpec("demo", "lookup", "d", {"type": "object", "properties": {}})
    tool = make_mcp_tools(c.config, specs=[spec], client=c)[0]
    assert tool.call(_spec="x", client="y").success is True
    assert fake.calls[0].body["params"]["arguments"] == {"_spec": "x", "client": "y"}
    # "self" cannot go through ragleap_tools.Tool.call (declared call(self, **kwargs) in
    # ragleap-tools 0.4.0, so the keyword collides with the method's own parameter), but
    # our handler itself accepts any argument name.
    assert tool.handler(**{"self": "z"}).success is True
    assert fake.calls[1].body["params"]["arguments"] == {"self": "z"}
