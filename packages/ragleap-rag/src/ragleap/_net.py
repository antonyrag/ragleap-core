"""Guarded HTTP(S) GET used by ingest_url().

Every hop (the first URL and each redirect) is validated: http/https only,
no credentials in the URL, and every address the host resolves to must be
public. The connection then goes to the validated address itself, so a
second DNS lookup cannot swap in a different one. Response size and time
are capped. Pass allow_private=True to reach private networks (intranet).

Known limits: name resolution (getaddrinfo) is not covered by the
timeouts; 6to4/NAT64 addresses that embed an IPv4 address are not
specially handled; proxy environment variables are not honored.
"""
import http.client
import ipaddress
import socket
import ssl
import time
import zlib
from typing import Optional
from urllib.parse import urljoin, urlsplit

MAX_REDIRECTS = 3
TIMEOUT = 15
TOTAL_TIMEOUT = 30
MAX_BYTES = 10 * 1024 * 1024
USER_AGENT = "ragleap-rag/ingest_url"
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class UnsafeURLError(ValueError):
    """The URL, or a redirect target, was refused by the network guard."""


def _resolve(host: str, port: int, allow_private: bool) -> str:
    """Resolve once; every address must be public unless allow_private."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise OSError(f"could not resolve host: {e}") from e
    ips = []
    for info in infos:
        ip = info[4][0].split("%")[0]
        addr = ipaddress.ip_address(ip)
        mapped = getattr(addr, "ipv4_mapped", None)
        if mapped is not None:
            addr = mapped
        if not allow_private and (not addr.is_global or addr.is_multicast):
            raise UnsafeURLError("refused: the host resolves to a non-public address")
        ips.append(ip)
    if not ips:
        raise OSError("host did not resolve")
    return ips[0]


def _open(scheme: str, host: str, port: int, ip: str, timeout: float):
    raw = socket.create_connection((ip, port), timeout=timeout)
    if scheme == "http":
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.sock = raw
        return conn
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        tls = ctx.wrap_socket(raw, server_hostname=host)
    except Exception:
        raw.close()
        raise
    conn = http.client.HTTPSConnection(host, port, timeout=timeout)
    conn.sock = tls
    return conn


def fetch_public(
    url: str,
    *,
    allow_private: bool = False,
    max_bytes: int = MAX_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    timeout: float = TIMEOUT,
    total_timeout: float = TOTAL_TIMEOUT,
) -> Optional[bytes]:
    """Return the response body, or None for a non-200 answer, too many
    redirects, a body over max_bytes (raw or decompressed), or an unsupported Content-Encoding.
    Raises UnsafeURLError when the guard refuses; network errors
    (OSError, ssl errors, http.client.HTTPException) propagate."""
    deadline = time.monotonic() + total_timeout
    current = url
    for _ in range(max_redirects + 1):
        parts = urlsplit(current)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            raise UnsafeURLError("refused: only http and https URLs are allowed")
        if parts.username or parts.password:
            raise UnsafeURLError("refused: credentials in the URL")
        host = (parts.hostname or "").rstrip(".")
        if not host:
            raise UnsafeURLError("refused: the URL has no host")
        try:
            port = parts.port or (443 if scheme == "https" else 80)
        except ValueError:
            raise UnsafeURLError("refused: invalid port")
        ip = _resolve(host, port, allow_private)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        conn = _open(scheme, host, port, ip, timeout)
        try:
            conn.request("GET", path, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5",
                "Accept-Encoding": "gzip",
                "Connection": "close",
            })
            resp = conn.getresponse()
            if resp.status in _REDIRECT_STATUSES:
                location = resp.getheader("Location")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            if resp.status != 200:
                return None
            encoding = (resp.getheader("Content-Encoding") or "identity").strip().lower()
            if encoding not in ("identity", "gzip", "x-gzip", "deflate"):
                return None
            declared = resp.getheader("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                return None
            decoder = None
            if encoding in ("gzip", "x-gzip"):
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            elif encoding == "deflate":
                decoder = zlib.decompressobj(zlib.MAX_WBITS)  # zlib-wrapped only
            body = bytearray()
            received = 0
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    if decoder is not None:
                        try:
                            body += decoder.flush()
                        except zlib.error:
                            return None
                        if not decoder.eof or len(body) > max_bytes:
                            return None
                    return bytes(body)
                received += len(chunk)
                if received > max_bytes:
                    return None
                if decoder is None:
                    body += chunk
                else:
                    try:
                        body += decoder.decompress(chunk, max_bytes + 1 - len(body))
                    except zlib.error:
                        return None
                if len(body) > max_bytes:
                    return None
                if time.monotonic() > deadline:
                    return None
        finally:
            conn.close()
    return None
