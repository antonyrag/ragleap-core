#!/usr/bin/env python3
"""Small read-only client for a running RagLeap Core server (standard library only).

Settings come from the environment:
  RAGLEAP_URL      server address, default http://localhost:8000
  RAGLEAP_API_KEY  the server's API key, if it has one (sent as the x-api-key header)

Subcommands: health, employees, ask. Nothing here uploads, edits or deletes data.
"""
import argparse
import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://localhost:8000"
TIMEOUT_SECONDS = 120
MAX_QUESTION_CHARS = 2000
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
ROLE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
KEY_RE = re.compile(r"^[\x21-\x7e]+$")


class ClientError(Exception):
    """A problem to show to the user in plain words."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _is_local(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def server_settings():
    raw = os.environ.get("RAGLEAP_URL", DEFAULT_URL).strip().rstrip("/") or DEFAULT_URL
    parsed = urllib.parse.urlparse(raw)
    try:
        ok = bool(parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username
                  and not parsed.password and not parsed.query and not parsed.fragment)
        parsed.port  # raises ValueError for a bad port
    except ValueError:
        ok = False
    if not ok:
        raise ClientError("RAGLEAP_URL must look like https://host or http://localhost:8000 "
                          "(no credentials, query or fragment).")
    key = os.environ.get("RAGLEAP_API_KEY", "").strip()
    if key and not KEY_RE.match(key):
        raise ClientError("RAGLEAP_API_KEY contains characters that cannot be sent in a header.")
    if key and parsed.scheme != "https" and not _is_local(parsed.hostname):
        raise ClientError("Refusing to send the API key over plain http to a non-local server. "
                          "Use an https address.")
    return raw, key


def _http_message(err):
    code = err.code
    if code == 401:
        return "The server rejected the API key (401). Set RAGLEAP_API_KEY to the server's key."
    if code == 429:
        wait = err.headers.get("Retry-After", "") if err.headers else ""
        return "Too many requests or failed logins (429). Wait " + \
            (wait + " seconds" if wait.isdigit() else "a while") + " before trying again."
    if code in (301, 302, 303, 307, 308):
        return "The server redirected the request. Update RAGLEAP_URL to the final https address."
    if code == 400:
        return "The server rejected the request (400). Check the question and the role."
    return "The server answered with an error (HTTP %d)." % code


def call(method, path, params=None):
    base, key = server_settings()
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json", "User-Agent": "ragleap-agent-skill/0.1"}
    if key:
        headers["x-api-key"] = key
    request = urllib.request.Request(url, data=(b"" if method == "POST" else None),
                                     headers=headers, method=method)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as err:
        raise ClientError(_http_message(err)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ClientError("Could not reach the RagLeap server. Check RAGLEAP_URL and that the server is running.") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise ClientError("The server's answer was too large to read.")
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        raise ClientError("The server did not return JSON. Is RAGLEAP_URL pointing at RagLeap?") from None


def cmd_health(_args):
    data = call("GET", "/health")
    print("RagLeap answers: %s" % (data.get("status", "ok") if isinstance(data, dict) else "ok"))


def cmd_employees(args):
    data = call("GET", "/employees", {"active_only": "true"} if args.active_only else None)
    roles = data.get("roles", []) if isinstance(data, dict) else []
    if args.json:
        print(json.dumps(roles))
        return
    for item in roles:
        if isinstance(item, dict):
            name = str(item.get("display_name") or "")
            state = "" if item.get("is_active", True) else " (off)"
            print("%s%s%s" % (str(item.get("role", "?")), " - " + name if name else "", state))
        else:
            print(str(item)[:100])


def cmd_ask(args):
    question = " ".join(args.question).strip()
    if not question:
        raise ClientError("Give a question to ask.")
    if len(question) > MAX_QUESTION_CHARS:
        raise ClientError("The question is longer than %d characters." % MAX_QUESTION_CHARS)
    if args.role and not ROLE_RE.match(args.role):
        raise ClientError("A role name may only use letters, digits, - and _.")
    params = {"question": question, "top_k": args.top_k}
    if args.role:
        params["role"] = args.role
    data = call("POST", "/chat", params)
    if not isinstance(data, dict) or "answer" not in data:
        raise ClientError("Unexpected answer from the server.")
    if args.json:
        print(json.dumps({"answer": data.get("answer"), "sources": data.get("sources", []),
                          "chunks_used": data.get("chunks_used", 0)}))
        return
    print(str(data.get("answer", "")).strip())
    sources = data.get("sources") or []
    if sources:
        print("\nSources: " + ", ".join(str(s) for s in sources[:20]))


def build_parser():
    parser = argparse.ArgumentParser(prog="ragleap_client.py", description="Read-only client for a RagLeap Core server.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="check that the server answers")
    emp = sub.add_parser("employees", help="list the AI employee roles")
    emp.add_argument("--active-only", action="store_true")
    emp.add_argument("--json", action="store_true")
    ask = sub.add_parser("ask", help="ask a question grounded in the ingested documents")
    ask.add_argument("question", nargs="+")
    ask.add_argument("--role")
    ask.add_argument("--top-k", type=int, default=5, choices=range(1, 21), metavar="N")
    ask.add_argument("--json", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        {"health": cmd_health, "employees": cmd_employees, "ask": cmd_ask}[args.command](args)
    except ClientError as err:
        print("ragleap: %s" % err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
