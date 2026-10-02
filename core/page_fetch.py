"""
Read-only web page fetching for AI Employees (the fetch_page action tool).

Owner-configured only:
  BROWSER_FETCH_ENABLED=true
  BROWSER_ALLOWED_DOMAINS=docs.example.com,*.wiki.example.org
    ("*." entries match subdomains only, never the bare domain or a TLD.)
The model supplies only a URL, and it must pass every check below.
- https only, port 443, no credentials, no IP literals, host on the allowlist
- DNS is resolved ONCE; every address must be globally routable; the TCP
  connection is then made to that exact IP (pinned) with TLS verified against
  the hostname, so DNS rebinding cannot swap in an internal address
- redirects are followed manually (max 3) and every hop is re-validated
- no cookies, no auth headers, fixed User-Agent, identity encoding
- streamed with a size cap and wall-clock deadline; text/html, text/plain and
  application/json only; HTML is reduced to visible text (stdlib parser)
fetch_page never raises. v1: the text goes back to the owner only; it is not
fed back to the model.
"""
import html.parser
import http.client
import ipaddress
import logging
import os
import re
import socket
import ssl
import time
from typing import List, Tuple
from urllib.parse import urljoin, urlsplit

logger = logging.getLogger(__name__)

MAX_URL_CHARS = 300
MAX_REDIRECTS = 3
TIMEOUT = 15
TOTAL_TIMEOUT = 20
MAX_BYTES = 1024 * 1024
MAX_RESULT_CHARS = 4000
ALLOWED_TYPES = ("text/html", "text/plain", "application/json")
USER_AGENT = "Mozilla/5.0 (compatible; RagLeapBot/1.0; +https://github.com/antonyrag/ragleap-core)"


def allowed_domains() -> List[str]:
    out = []
    for item in os.environ.get("BROWSER_ALLOWED_DOMAINS", "").split(","):
        item = item.strip().lower().rstrip(".")
        if item and re.fullmatch(r"(\*\.)?[a-z0-9-]+(\.[a-z0-9-]+)+", item) and item not in out:
            out.append(item)
    return out


def enabled() -> bool:
    return (os.environ.get("BROWSER_FETCH_ENABLED", "").strip().lower() == "true"
            and bool(allowed_domains()))


def host_allowed(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    for pat in allowed_domains():
        if pat.startswith("*."):
            if host.endswith(pat[1:]):
                return True
        elif host == pat:
            return True
    return False


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def validate_url(url: str) -> Tuple[str, str]:
    """Return (host, path_with_query) or raise ValueError."""
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_CHARS:
        raise ValueError("bad url length")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("invalid characters in url")
    p = urlsplit(url)
    if p.scheme != "https":
        raise ValueError("https only")
    if p.username or p.password or "@" in p.netloc:
        raise ValueError("credentials not allowed")
    try:
        port = p.port
    except ValueError:
        raise ValueError("bad port")
    if port not in (None, 443):
        raise ValueError("port not allowed")
    host = (p.hostname or "").lower().rstrip(".")
    if not host or not host.isascii():
        raise ValueError("bad host")
    if _is_ip(host):
        raise ValueError("ip addresses not allowed")
    if not host_allowed(host):
        raise ValueError("host not on the allowlist")
    path = p.path or "/"
    if p.query:
        path += "?" + p.query
    return host, path


def resolve_public(host: str) -> str:
    """Resolve once; every address must be public. Returns the IP to pin."""
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ips = []
    for info in infos:
        ip = info[4][0].split("%")[0]
        a = ipaddress.ip_address(ip)
        mapped = getattr(a, "ipv4_mapped", None)
        if mapped is not None:
            a = mapped
        if not a.is_global or a.is_multicast:
            raise ValueError("host resolves to a non-public address")
        ips.append(ip)
    if not ips:
        raise ValueError("host did not resolve")
    return ips[0]


def _request(host: str, ip: str, path: str) -> Tuple[int, str, str, bytes]:
    """One GET to the pinned IP. Returns (status, location, content_type, body)."""
    deadline = time.monotonic() + TOTAL_TIMEOUT
    raw = socket.create_connection((ip, 443), timeout=TIMEOUT)
    try:
        tls = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
    except Exception:
        raw.close()
        raise
    conn = http.client.HTTPSConnection(host, 443, timeout=TIMEOUT)
    conn.sock = tls
    try:
        conn.request("GET", path, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,text/plain,application/json;q=0.9",
            "Accept-Encoding": "identity",
            "Connection": "close",
        })
        resp = conn.getresponse()
        status = resp.status
        location = resp.getheader("Location") or ""
        ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
        if status != 200:
            return status, location, ctype, b""
        body = bytearray()
        while True:
            chunk = resp.read(8192)
            if not chunk:
                break
            body += chunk
            if len(body) > MAX_BYTES:
                raise ValueError("response too large")
            if time.monotonic() > deadline:
                raise ValueError("response too slow")
        return status, location, ctype, bytes(body)
    finally:
        conn.close()


_SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "object", "head"}
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed",
         "source", "track", "wbr"}
_BLOCK = {"p", "div", "br", "li", "tr", "ul", "ol", "table", "section", "article", "header",
          "footer", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}


class _Text(html.parser.HTMLParser):
    """Visible text only: drops script/style/head and elements hidden by attribute."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.hidden = [], [], 0

    @staticmethod
    def _is_hidden(tag, attrs):
        if tag in _SKIP:
            return True
        a = {k: (v or "") for k, v in attrs}
        style = a.get("style", "").replace(" ", "").lower()
        return ("hidden" in a or a.get("aria-hidden", "").lower() == "true"
                or "display:none" in style or "visibility:hidden" in style)

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK:
            self.out.append("\n")
        if tag in _VOID:
            return
        h = self._is_hidden(tag, attrs)
        self.stack.append(h)
        self.hidden += 1 if h else 0

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCK:
            self.out.append("\n")
        if tag in _VOID:
            return
        if self.stack and self.stack.pop():
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.out.append(data)


def html_to_text(markup: str) -> str:
    p = _Text()
    try:
        p.feed(markup)
        p.close()
    except Exception:
        pass
    s = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    s = "\n".join(line.strip() for line in s.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def fetch_page(url: str) -> str:
    try:
        if not enabled():
            return "Page fetch: refused (not enabled)"
        current = (url or "").strip()
        for _ in range(MAX_REDIRECTS + 1):
            host, path = validate_url(current)
            ip = resolve_public(host)
            status, location, ctype, body = _request(host, ip, path)
            if 300 <= status < 400:
                if not location:
                    raise ValueError("redirect without a location")
                current = urljoin(current, location)
                continue
            if status != 200:
                return f"Page fetch: HTTP {status} from {host}"
            if ctype not in ALLOWED_TYPES:
                return f"Page fetch: refused (content type {ctype or 'unknown'} not allowed)"
            text = body.decode("utf-8", "replace")
            if ctype == "text/html":
                text = html_to_text(text)
            head = f"Page fetch: https://{host}{path[:120]} (HTTP 200)\n"
            return (head + text.strip())[:MAX_RESULT_CHARS]
        return "Page fetch: refused (too many redirects)"
    except ValueError as e:
        return f"Page fetch: refused ({e})"
    except Exception as e:
        logger.error("Page fetch failed: %s", e)
        return "Page fetch: failed; see server logs."
