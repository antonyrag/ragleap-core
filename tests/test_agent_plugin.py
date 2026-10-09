import importlib.util
import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / ".codex-plugin" / "plugin.json"
SKILL_DIR = ROOT / "skills" / "ragleap"
SCRIPT = SKILL_DIR / "scripts" / "ragleap_client.py"

spec = importlib.util.spec_from_file_location("ragleap_client", SCRIPT)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class Fake:
    def __init__(self, status=200, body=None, headers=None, raw=None):
        self.status, self.headers_out, self.requests = status, headers or {}, []
        self.body = json.dumps(body if body is not None else {}).encode() if raw is None else raw
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _go(self):
                fake.requests.append({"method": self.command, "path": self.path,
                                      "headers": {k.lower(): v for k, v in self.headers.items()}})
                self.send_response(fake.status)
                for k, v in fake.headers_out.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(fake.body)))
                self.end_headers()
                self.wfile.write(fake.body)

            do_GET = _go
            do_POST = _go

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def serve(monkeypatch):
    made = []
    monkeypatch.delenv("RAGLEAP_API_KEY", raising=False)

    def make(**kw):
        f = Fake(**kw)
        made.append(f)
        monkeypatch.setenv("RAGLEAP_URL", f.url)
        return f
    yield make
    for f in made:
        f.close()


def test_manifest_has_what_the_catalog_and_scanner_need():
    m = json.loads(PLUGIN.read_text())
    for field in ("name", "version", "description", "author", "homepage", "repository", "license", "keywords", "skills"):
        assert m.get(field), field
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", m["name"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", m["version"])
    skills = (PLUGIN.parent.parent / m["skills"]).resolve()
    assert skills.is_dir() and skills.is_relative_to(ROOT)
    assert (skills / "ragleap" / "SKILL.md").is_file()
    assert m["license"] == "MIT" and (ROOT / "LICENSE").is_file()


def test_skill_file_is_well_formed_and_plain():
    text = (SKILL_DIR / "SKILL.md").read_text()
    head = text.split("---")[1]
    assert re.search(r"(?m)^name: ragleap$", head) and re.search(r"(?m)^description: .{40,}", head)
    assert "://" not in text and "/home/" not in text and "/Users/" not in text
    for word in ("curl ", "wget ", "sudo ", "rm -rf"):
        assert word not in text.lower()


def test_script_has_no_dynamic_code_or_shell():
    src = SCRIPT.read_text()
    for bad in ("ev" + "al(", "ex" + "ec(", "sub" + "process", "os." + "system", "shell=" + "True"):
        assert bad not in src, bad


def test_ask_sends_the_question_and_prints_answer_and_sources(serve, capsys):
    f = serve(body={"answer": "Hello there", "sources": ["a.txt", "b.pdf"], "chunks_used": 2, "provider_used": "x"})
    assert client.main(["ask", "what", "is", "RagLeap?", "--role", "support", "--top-k", "3"]) == 0
    out = capsys.readouterr().out
    assert "Hello there" in out and "Sources: a.txt, b.pdf" in out
    r = f.requests[0]
    parsed = urllib.parse.urlparse(r["path"])
    assert r["method"] == "POST" and parsed.path == "/chat"
    assert urllib.parse.parse_qs(parsed.query) == {"question": ["what is RagLeap?"], "top_k": ["3"], "role": ["support"]}


def test_key_is_sent_as_a_header_only_when_set_and_never_printed(serve, monkeypatch, capsys):
    f = serve(body={"status": "ok"})
    assert client.main(["health"]) == 0
    assert "x-api-key" not in f.requests[0]["headers"]
    monkeypatch.setenv("RAGLEAP_API_KEY", "example-key-value")
    assert client.main(["health"]) == 0
    assert f.requests[1]["headers"]["x-api-key"] == "example-key-value"
    cap = capsys.readouterr()
    assert "example-key-value" not in cap.out + cap.err and "example-key-value" not in f.requests[1]["path"]


def test_employees_lists_roles_and_marks_switched_off_ones(serve, capsys):
    f = serve(body={"roles": [{"role": "sales", "display_name": "Sales", "is_active": True},
                              {"role": "legal_intake", "display_name": "Legal intake", "is_active": False}, "odd"]})
    assert client.main(["employees"]) == 0
    assert capsys.readouterr().out.splitlines() == ["sales - Sales", "legal_intake - Legal intake (off)", "odd"]
    client.main(["employees", "--active-only"])
    assert "active_only=true" in f.requests[1]["path"]


def test_refuses_to_send_the_key_over_plain_http_to_a_remote_host(monkeypatch, capsys):
    monkeypatch.setenv("RAGLEAP_URL", "http://203.0.113.9:8000")
    monkeypatch.setenv("RAGLEAP_API_KEY", "example-key-value")
    assert client.main(["health"]) == 1
    assert "plain http" in capsys.readouterr().err


def test_key_is_allowed_over_https_and_to_local_http(monkeypatch):
    monkeypatch.setenv("RAGLEAP_API_KEY", "example-key-value")
    for url in ("https://rag.example.com", "http://localhost:8000", "http://127.0.0.1:9", "http://[::1]:8000"):
        monkeypatch.setenv("RAGLEAP_URL", url)
        assert client.server_settings()[1] == "example-key-value"


@pytest.mark.parametrize("bad", ["ftp://x", "http://user:pw@host", "http://host?a=1", "http://host#f",
                                 "http://host:notaport", "nothing", "http://"])
def test_bad_addresses_are_rejected(monkeypatch, bad):
    monkeypatch.setenv("RAGLEAP_URL", bad)
    with pytest.raises(client.ClientError):
        client.server_settings()


def test_a_key_with_odd_characters_is_refused(monkeypatch, capsys):
    monkeypatch.setenv("RAGLEAP_API_KEY", "bad\nkey")
    assert client.main(["health"]) == 1
    assert "characters" in capsys.readouterr().err


def test_redirects_are_not_followed_so_the_key_cannot_leak(serve, monkeypatch, capsys):
    other = Fake(body={"status": "ok"})
    try:
        serve(status=302, headers={"Location": other.url + "/"})
        monkeypatch.setenv("RAGLEAP_API_KEY", "example-key-value")
        assert client.main(["health"]) == 1
        assert other.requests == [] and "redirected" in capsys.readouterr().err
    finally:
        other.close()


@pytest.mark.parametrize("status,headers,expect", [(401, {}, "401"), (429, {"Retry-After": "7"}, "7 seconds"),
                                                   (400, {}, "400"), (500, {}, "HTTP 500")])
def test_http_errors_are_explained_without_echoing_the_body(serve, capsys, status, headers, expect):
    serve(status=status, headers=headers, body={"detail": "secret-detail-xyz"})
    assert client.main(["ask", "hi"]) == 1
    err = capsys.readouterr().err
    assert expect in err and "secret-detail-xyz" not in err


def test_non_json_unexpected_and_unreachable(serve, monkeypatch, capsys):
    serve(raw=b"<html>nope</html>")
    assert client.main(["health"]) == 1 and "JSON" in capsys.readouterr().err
    serve(body={"nope": 1})
    assert client.main(["ask", "hi"]) == 1 and "Unexpected" in capsys.readouterr().err
    monkeypatch.setenv("RAGLEAP_URL", "http://127.0.0.1:1")
    assert client.main(["health"]) == 1 and "Could not reach" in capsys.readouterr().err


def test_question_and_role_are_validated_before_any_request(serve):
    f = serve(body={"answer": "x"})
    assert client.main(["ask", "   "]) == 1
    assert client.main(["ask", "x" * 2001]) == 1
    assert client.main(["ask", "hi", "--role", "bad role!"]) == 1
    assert f.requests == []
    with pytest.raises(SystemExit) as e:
        client.main(["ask", "hi", "--top-k", "99"])
    assert e.value.code == 2


def test_json_output_has_only_the_expected_fields(serve, capsys):
    serve(body={"answer": "A", "sources": ["s"], "chunks_used": 1, "usage": {"tokens": 5}, "provider_used": "p"})
    assert client.main(["ask", "hi", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"answer": "A", "sources": ["s"], "chunks_used": 1}
