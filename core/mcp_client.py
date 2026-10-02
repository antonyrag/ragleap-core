"""
Minimal MCP (Model Context Protocol) client over Streamable HTTP, no SDK.

Owner-configured only, same trust model as WEBHOOK_TARGETS:
  MCP_SERVERS=name=https://host/mcp,name2=https://...   (server name -> URL)
  MCP_ALLOWED_TOOLS=name.tool,name.other_tool           (exact tools allowed)
  MCP_TOKEN_<NAME>=...                                  (optional bearer token)
The model only ever picks a target from the allowlist and supplies JSON
arguments; it never chooses a URL, command or token. HTTPS to public
addresses only, redirects off, response size capped. call_tool never raises.
v1 scope: remote HTTP servers, static bearer tokens, one-shot calls.
"""
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import requests

from core import action_senders

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20
MAX_RESPONSE_BYTES = 256 * 1024
MAX_RESULT_CHARS = 2000
PROTOCOL_VERSION = "2025-06-18"


def servers() -> Dict[str, str]:
    out = {}
    for item in os.environ.get("MCP_SERVERS", "").split(","):
        if "=" not in item:
            continue
        name, url = item.split("=", 1)
        name, url = name.strip(), url.strip()
        if name and "." not in name and url:
            out[name] = url
    return out


def allowed_targets() -> List[str]:
    """'server.tool' entries from MCP_ALLOWED_TOOLS whose server is configured."""
    srv = servers()
    out = []
    for item in os.environ.get("MCP_ALLOWED_TOOLS", "").split(","):
        item = item.strip()
        if "." not in item:
            continue
        s, t = item.split(".", 1)
        if s in srv and t and item not in out:
            out.append(item)
    return sorted(out)


def _token(server: str) -> str:
    return os.environ.get("MCP_TOKEN_" + re.sub(r"[^A-Za-z0-9]", "_", server).upper(), "").strip()


def _rpc(url: str, headers: Dict, payload: Dict, expect_id: Optional[int] = None) -> Tuple[Optional[Dict], Dict]:
    resp = requests.post(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT,
                         allow_redirects=False, stream=True)
    try:
        if not 200 <= resp.status_code < 300:
            raise ValueError(f"HTTP {resp.status_code}")
        if expect_id is None:
            return None, dict(resp.headers)
        data = b""
        for chunk in resp.iter_content(8192):
            data += chunk
            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("response too large")
        text = data.decode("utf-8", "replace")
        obj = None
        if "text/event-stream" in resp.headers.get("Content-Type", ""):
            for line in text.splitlines():
                if line.startswith("data:"):
                    try:
                        cand = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    if isinstance(cand, dict) and cand.get("id") == expect_id:
                        obj = cand
                        break
        else:
            cand = json.loads(text)
            obj = cand if isinstance(cand, dict) else None
        if not obj:
            raise ValueError("no JSON-RPC response")
        if obj.get("error"):
            raise ValueError(f"server error: {str(obj['error'])[:200]}")
        return obj, dict(resp.headers)
    finally:
        resp.close()


def call_tool(target: str, content: str) -> str:
    """Call one allowlisted MCP tool. Returns a result string; never raises."""
    target = (target or "").strip()
    try:
        if target not in allowed_targets():
            logger.error("MCP target '%s' is not in MCP_ALLOWED_TOOLS - refused", target)
            return f"MCP {target}: refused (not allowlisted)"
        server, tool = target.split(".", 1)
        url = servers()[server]
        if not action_senders._is_public_https_url(url):
            logger.error("MCP server '%s' is not a public https URL - refused", server)
            return f"MCP {target}: refused (server URL not allowed)"
        args = json.loads(content) if (content or "").strip() else {}
        if not isinstance(args, dict):
            return f"MCP {target}: refused (arguments must be a JSON object)"

        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        tok = _token(server)
        if tok:
            headers["Authorization"] = f"Bearer {tok}"

        init, h = _rpc(url, headers, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "ragleap-core", "version": "0.1"}}}, 1)
        sid = {k.lower(): v for k, v in h.items()}.get("mcp-session-id")
        if sid:
            headers["Mcp-Session-Id"] = sid
        headers["MCP-Protocol-Version"] = ((init or {}).get("result") or {}).get("protocolVersion") or PROTOCOL_VERSION
        _rpc(url, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        res, _h = _rpc(url, headers, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool, "arguments": args}}, 2)

        result = (res or {}).get("result") or {}
        parts = [c.get("text", "") for c in (result.get("content") or [])
                 if isinstance(c, dict) and c.get("type") == "text"]
        status = "error" if result.get("isError") else "ok"
        return f"MCP {target}: {status}\n{chr(10).join(parts)}"[:MAX_RESULT_CHARS]
    except Exception as e:
        logger.error("MCP call %s failed: %s", target, e)
        return f"MCP {target}: failed; see server logs."
