"""Model callables for Agent: an OpenAI-compatible chat-completions adapter.

Standard library only. The base URL is set by the owner in code; do not build it
from untrusted input (there is no address guard). The API key is passed in, never
read from the environment. Errors carry a status code or an exception type, never a
response body, a URL or a key. Redirects are refused. Agent still validates every
proposal, whichever mode produced it.
"""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from ragleap_tools import Tool

from ragleap_agents.agent import SUMMARY_PROMPT_PREFIX, parse_plan

MAX_RETRIES = 5
MAX_RETRY_AFTER = 30.0
_RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """A model call failed. The message never holds a response body, URL or key."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Retry(Exception):
    def __init__(self, what: str, retry_after: Optional[str] = None):
        super().__init__(what)
        self.what, self.retry_after = what, retry_after


def openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    *,
    mode: str = "json",
    tools: Optional[List[Tool]] = None,
    temperature: Optional[float] = 0.0,
    timeout: float = 30.0,
    max_retries: int = 2,
    backoff: float = 1.0,
    max_response_bytes: int = 1_000_000,
    allow_insecure_http: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[str], str]:
    """Return llm(prompt) -> str for Agent, over POST {base_url}/chat/completions.

    mode="json": the model replies with the JSON action as text.
    mode="native": the model may use tool calling; the first tool call is re-serialised
    as the JSON action, and a reply with no tool call becomes an explicit done.
    Malformed tool-call arguments become an empty reply, which Agent stops on.
    """
    if mode not in ("json", "native"):
        raise ValueError("mode must be 'json' or 'native'")
    if mode == "native" and not tools:
        raise ValueError("native mode needs the tools list")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("api_key is required")
    p = urllib.parse.urlsplit(base_url)
    if p.scheme not in ("https", "http") or not p.hostname:
        raise ValueError("base_url must be an http(s) URL")
    if p.scheme == "http" and not allow_insecure_http:
        raise ValueError("https is required (allow_insecure_http=True is for local testing)")
    if p.username or p.password or p.query or p.fragment:
        raise ValueError("base_url must not contain credentials, a query or a fragment")
    url = base_url.rstrip("/") + "/chat/completions"
    schemas = [t.to_openai_schema() for t in tools] if tools else []
    retries = max(0, min(int(max_retries), MAX_RETRIES))
    opener = urllib.request.build_opener(_NoRedirect)
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json", "Accept": "application/json"}

    def once(payload: Dict[str, Any]) -> Any:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read(max_response_bytes + 1)
        except urllib.error.HTTPError as e:
            ra = e.headers.get("Retry-After") if e.headers else None
            code = e.code
            e.close()
            if code in _RETRY_STATUS:
                raise _Retry("status %d" % code, ra) from None
            raise ProviderError("request failed: status %d" % code) from None
        except (OSError, http.client.HTTPException) as e:
            raise _Retry(type(e).__name__) from None
        if len(raw) > max_response_bytes:
            raise ProviderError("response too large")
        try:
            return json.loads(raw)
        except ValueError:
            raise ProviderError("response was not valid JSON") from None

    def delay(attempt: int, retry_after: Optional[str]) -> float:
        try:
            if retry_after is not None:
                return min(max(float(retry_after), 0.0), MAX_RETRY_AFTER)
        except ValueError:
            pass
        return backoff * (2 ** attempt)

    def llm(prompt: str) -> str:
        summary = prompt.startswith(SUMMARY_PROMPT_PREFIX)
        use_tools = mode == "native" and not summary
        payload: Dict[str, Any] = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        if temperature is not None:
            payload["temperature"] = temperature
        if use_tools:
            payload["tools"], payload["tool_choice"] = schemas, "auto"
        for attempt in range(retries + 1):
            try:
                data = once(payload)
                break
            except _Retry as r:
                if attempt >= retries:
                    raise ProviderError("request failed: " + r.what) from None
                sleep(delay(attempt, r.retry_after))
        return _reply(data, use_tools)

    return llm


def _reply(data: Any, native: bool) -> str:
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError("unexpected response shape") from None
    if not isinstance(msg, dict):
        raise ProviderError("unexpected response shape")
    content = msg.get("content")
    text = content if isinstance(content, str) else ""
    calls = msg.get("tool_calls")
    if native and isinstance(calls, list) and calls:
        fn = calls[0].get("function") if isinstance(calls[0], dict) else None
        fn = fn if isinstance(fn, dict) else {}
        name, raw = fn.get("name"), fn.get("arguments")
        if not isinstance(name, str) or not name:
            return ""
        try:
            args = {} if raw in (None, "") else (json.loads(raw) if isinstance(raw, str) else raw)
        except ValueError:
            return ""
        return json.dumps({"tool": name, "arguments": args}) if isinstance(args, dict) else ""
    if native and text.strip() and parse_plan(text) is None:
        return json.dumps({"tool": "done", "answer": text})
    return text
