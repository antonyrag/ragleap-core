"""openai_compatible against a real local HTTP server (127.0.0.1). No external network."""
import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from ragleap_tools import Tool, ToolResult

from ragleap_agents import Agent, Policy, ProviderError, TRUSTED, openai_compatible
from ragleap_agents.agent import SUMMARY_PROMPT_PREFIX

KEY = "sk-SECRET-KEY-123"
BODY_SECRET = "BODY-SECRET-xyz"


def completion(content=None, tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg}]}


def call(name, args):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}


class Srv:
    """script items: (status, headers, body) or (status, headers, body, delay_seconds)."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                       "body": json.loads(self.rfile.read(n) or b"{}")})
                item = outer.script.pop(0) if outer.script else (500, {}, {})
                status, hdrs, body = item[:3]
                if len(item) > 3:
                    threading.Event().wait(item[3])
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                try:
                    self.send_response(status)
                    for k, v in hdrs.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.01), daemon=True).start()
        self.url = "http://127.0.0.1:%d/v1" % self.httpd.server_address[1]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def srv():
    made = []

    def make(script):
        s = Srv(script)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


def calc_tool():
    return Tool("calc", "Evaluate", {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
                lambda expression: ToolResult(True, "42"))


def make(s, **kw):
    kw.setdefault("sleep", lambda d: None)
    kw.setdefault("allow_insecure_http", True)
    return openai_compatible(s.url, KEY, "m1", **kw)


# ---- configuration ----

@pytest.mark.parametrize("url,kw", [
    ("http://127.0.0.1:1/v1", {}),
    ("https://user:pw@example.com/v1", {}),
    ("https://example.com/v1?x=1", {}),
    ("https://example.com/v1#f", {}),
    ("ftp://example.com/v1", {}),
    ("https:///v1", {}),
])
def test_unsafe_or_malformed_base_urls_are_refused(url, kw):
    with pytest.raises(ValueError):
        openai_compatible(url, KEY, "m", **kw)


def test_missing_key_bad_mode_and_native_without_tools_are_refused():
    for kw in ({"api_key": ""}, {"api_key": "  "}):
        with pytest.raises(ValueError):
            openai_compatible("https://example.com/v1", kw["api_key"], "m")
    with pytest.raises(ValueError):
        openai_compatible("https://example.com/v1", KEY, "m", mode="x")
    with pytest.raises(ValueError):
        openai_compatible("https://example.com/v1", KEY, "m", mode="native")


# ---- json mode ----

def test_json_mode_sends_the_prompt_and_returns_the_text(srv):
    s = srv([(200, {}, completion('{"tool": "done"}'))])
    assert make(s)("hello") == '{"tool": "done"}'
    r = s.requests[0]
    assert r["path"] == "/v1/chat/completions" and r["auth"] == "Bearer " + KEY
    assert r["body"]["model"] == "m1" and r["body"]["messages"] == [{"role": "user", "content": "hello"}]
    assert "tools" not in r["body"] and r["body"]["temperature"] == 0.0


def test_temperature_can_be_omitted(srv):
    s = srv([(200, {}, completion("x"))])
    make(s, temperature=None)("p")
    assert "temperature" not in s.requests[0]["body"]


def test_null_or_non_string_content_is_an_empty_reply(srv):
    s = srv([(200, {}, completion(None)), (200, {}, {"choices": [{"message": {"content": ["a"]}}]})])
    f = make(s)
    assert f("p") == "" and f("p") == ""


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": "x"}]}, {"choices": [1]}])
def test_unexpected_shapes_raise_provider_error(srv, body):
    with pytest.raises(ProviderError, match="unexpected response shape"):
        make(srv([(200, {}, body)]))("p")


def test_json_mode_runs_an_agent_end_to_end(srv):
    s = srv([(200, {}, completion(json.dumps({"tool": "calc", "arguments": {"expression": "6*7"}}))),
             (200, {}, completion('{"tool": "done"}')),
             (200, {}, completion("Computed 42."))])
    r = Agent(make(s), [calc_tool()], Policy(tools={"calc": TRUSTED})).run("what is 6*7")
    assert (r.status, r.answer, len(r.steps)) == ("done", "Computed 42.", 1)
    assert s.requests[2]["body"]["messages"][0]["content"].startswith(SUMMARY_PROMPT_PREFIX)


# ---- native mode ----

def test_native_mode_sends_tools_and_reserialises_the_first_tool_call(srv):
    s = srv([(200, {}, completion(None, [call("calc", {"expression": "1"}), call("other", {})]))])
    out = make(s, mode="native", tools=[calc_tool()])("go")
    assert json.loads(out) == {"tool": "calc", "arguments": {"expression": "1"}}
    b = s.requests[0]["body"]
    assert b["tool_choice"] == "auto" and b["tools"][0]["function"]["name"] == "calc"


def test_native_arguments_may_arrive_as_an_object_or_be_empty(srv):
    s = srv([(200, {}, completion(None, [{"function": {"name": "calc", "arguments": {"expression": "2"}}}])),
             (200, {}, completion(None, [{"function": {"name": "calc", "arguments": ""}}]))])
    f = make(s, mode="native", tools=[calc_tool()])
    assert json.loads(f("p"))["arguments"] == {"expression": "2"}
    assert json.loads(f("p"))["arguments"] == {}


@pytest.mark.parametrize("fn", [
    {"name": "calc", "arguments": '{"expression": '},
    {"name": "calc", "arguments": "[1, 2]"},
    {"name": "", "arguments": "{}"},
    {"arguments": "{}"},
])
def test_native_malformed_tool_calls_become_an_empty_reply(srv, fn):
    f = make(srv([(200, {}, completion(None, [{"function": fn}]))]), mode="native", tools=[calc_tool()])
    assert f("p") == ""


def test_native_prose_without_a_tool_call_becomes_an_explicit_done(srv):
    s = srv([(200, {}, completion("It is 42."))])
    out = json.loads(make(s, mode="native", tools=[calc_tool()])("p"))
    assert out == {"tool": "done", "answer": "It is 42."}


def test_native_json_text_passes_through_and_empty_stays_empty(srv):
    s = srv([(200, {}, completion('{"tool": "calc", "arguments": {"expression": "1"}}')), (200, {}, completion(""))])
    f = make(s, mode="native", tools=[calc_tool()])
    assert json.loads(f("p"))["tool"] == "calc" and f("p") == ""


def test_native_summary_call_is_plain_text_without_tools(srv):
    s = srv([(200, {}, completion("A summary."))])
    out = make(s, mode="native", tools=[calc_tool()])(SUMMARY_PROMPT_PREFIX + " (2-4 sentences) ...")
    assert out == "A summary." and "tools" not in s.requests[0]["body"]


def test_native_agent_end_to_end_and_bad_arguments_stop_the_run(srv):
    s = srv([(200, {}, completion(None, [call("calc", {"expression": "6*7"})])),
             (200, {}, completion("The answer is 42.")),
             (200, {}, completion("Summary."))])
    r = Agent(make(s, mode="native", tools=[calc_tool()]), [calc_tool()], Policy(tools={"calc": TRUSTED})).run("q")
    assert (r.status, r.answer, len(r.steps)) == ("done", "Summary.", 1)
    s2 = srv([(200, {}, completion(None, [call("calc", '{"expression": ')]))])
    r2 = Agent(make(s2, mode="native", tools=[calc_tool()]), [calc_tool()], Policy(tools={"calc": TRUSTED})).run("q")
    assert (r2.status, r2.stop_reason) == ("stopped", "unparseable_reply")


def test_a_native_tool_call_still_goes_through_agent_validation(srv):
    s = srv([(200, {}, completion(None, [call("calc", {"expression": 5})]))])
    r = Agent(make(s, mode="native", tools=[calc_tool()]), [calc_tool()], Policy(tools={"calc": TRUSTED})).run("q")
    assert (r.status, r.stop_reason, r.steps) == ("stopped", "invalid_plan", [])


# ---- retries ----

def test_retry_after_is_honoured_and_capped(srv):
    waits = []
    s = srv([(429, {"Retry-After": "2"}, {}), (429, {"Retry-After": "9999"}, {}), (200, {}, completion("ok"))])
    assert make(s, sleep=waits.append, max_retries=3)("p") == "ok" and waits == [2.0, 30.0]


def test_backoff_doubles_and_bad_retry_after_falls_back(srv):
    waits = []
    s = srv([(500, {}, {}), (503, {"Retry-After": "soon"}, {}), (200, {}, completion("ok"))])
    assert make(s, sleep=waits.append, backoff=1.5)("p") == "ok" and waits == [1.5, 3.0]


def test_retries_are_bounded_and_the_error_has_only_the_status(srv):
    s = srv([(500, {}, {"error": BODY_SECRET})] * 10)
    with pytest.raises(ProviderError) as e:
        make(s, max_retries=2)("p")
    assert str(e.value) == "request failed: status 500" and len(s.requests) == 3
    s2 = srv([(500, {}, {})] * 20)
    with pytest.raises(ProviderError):
        make(s2, max_retries=99)("p")
    assert len(s2.requests) == 6  # 1 + the cap of 5


def test_a_client_error_is_not_retried_and_leaks_nothing(srv):
    s = srv([(401, {}, {"error": BODY_SECRET + KEY}), (200, {}, completion("late"))])
    with pytest.raises(ProviderError) as e:
        make(s)("p")
    text = "".join(traceback.format_exception(type(e.value), e.value, e.value.__traceback__))
    assert str(e.value) == "request failed: status 401" and len(s.requests) == 1
    assert KEY not in text and BODY_SECRET not in text


def test_connection_failure_is_retried_then_reported_by_type_only():
    waits = []
    f = openai_compatible("http://127.0.0.1:1/v1", KEY, "m", allow_insecure_http=True, sleep=waits.append, max_retries=1)
    with pytest.raises(ProviderError) as e:
        f("p")
    assert str(e.value).startswith("request failed: ") and KEY not in str(e.value) and "127.0.0.1" not in str(e.value)
    assert len(waits) == 1


def test_a_slow_server_times_out(srv):
    s = srv([(200, {}, completion("late"), 1.0)])
    with pytest.raises(ProviderError, match="request failed"):
        make(s, timeout=0.2, max_retries=0)("p")


# ---- network safety ----

def test_redirects_are_refused_not_followed(srv):
    s = srv([(302, {"Location": "/elsewhere"}, {}), (200, {}, completion("followed"))])
    with pytest.raises(ProviderError, match="status 302"):
        make(s)("p")
    assert len(s.requests) == 1


def test_oversized_and_invalid_responses_are_rejected(srv):
    s = srv([(200, {}, completion("x" * 500))])
    with pytest.raises(ProviderError, match="too large"):
        make(s, max_response_bytes=100)("p")
    with pytest.raises(ProviderError, match="not valid JSON"):
        make(srv([(200, {}, b"<html>nope</html>")]))("p")


def test_the_summary_prompt_prefix_matches_what_agent_sends():
    seen = []
    tool = calc_tool()
    replies = [json.dumps({"tool": "calc", "arguments": {"expression": "1"}}), '{"tool": "done"}', "sum"]

    def llm(prompt):
        seen.append(prompt)
        return replies.pop(0)
    Agent(llm, [tool], Policy(tools={"calc": TRUSTED})).run("q")
    assert seen[-1].startswith(SUMMARY_PROMPT_PREFIX) and not seen[0].startswith(SUMMARY_PROMPT_PREFIX)
