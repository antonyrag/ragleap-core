"""
ragleap_tools.web_search

A pluggable web search tool - no hardcoded provider, matching this
ecosystem's BYOK philosophy (the same reasoning ragleap-rag applies to
its embedding/generation providers: "the library just always asks you
to know and specify your model," never a silent default).

Uses stdlib urllib.request rather than adding requests/httpx as a new
dependency - ragleap-tools has zero required dependencies today, and
both reference providers' APIs are simple JSON POST requests that
don't need more than the stdlib offers.

See docs/design/web-search-tool.md for the full design rationale.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List

from ragleap_tools._http import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TOTAL_TIMEOUT,
    fetch,
    validate_limits,
)
from ragleap_tools.base import Tool, ToolResult


class SearchProvider(ABC):
    """Abstract base for a web search backend. Implementations wrap a
    specific provider's API - callers construct the concrete provider
    they want and pass it to WebSearchConfig, no string-based registry
    or dispatch."""

    @abstractmethod
    def search(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """Returns a list of {"title": str, "url": str, "snippet": str}
        dicts. Must raise on failure (caught by search_web()'s handler,
        not by the provider itself) - providers are thin API wrappers,
        not responsible for the Tool/ToolResult error-handling
        convention the rest of this package follows."""
        raise NotImplementedError


@dataclass
class TavilySearchProvider(SearchProvider):
    """Tavily is purpose-built for LLM/RAG use cases - results already
    come back as clean, summarized content rather than raw search-engine
    snippets. api_key is required, no env var fallback, no default."""

    api_key: str
    base_url: str = "https://api.tavily.com/search"
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT

    def __post_init__(self) -> None:
        validate_limits(self.max_response_bytes, self.total_timeout)

    def search(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        # Bearer-header auth, per Tavily's current API docs. (An earlier
        # draft sent api_key in the request body - the older style, no
        # longer what the docs show.)
        payload = json.dumps({"query": query, "max_results": num_results}).encode("utf-8")
        request = urllib.request.Request(
            self.base_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        raw = fetch(request, max_bytes=self.max_response_bytes, total_timeout=self.total_timeout)
        data = json.loads(raw.decode("utf-8"))
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            }
            for item in data.get("results", [])
        ]


@dataclass
class SerperSearchProvider(SearchProvider):
    """Serper proxies real Google Search results - more raw than
    Tavily (titles/links/snippets as a user would see them on Google
    directly, not pre-summarized). api_key is required, no env var
    fallback, no default."""

    api_key: str
    base_url: str = "https://google.serper.dev/search"
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT

    def __post_init__(self) -> None:
        validate_limits(self.max_response_bytes, self.total_timeout)

    def search(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        payload = json.dumps({"q": query, "num": num_results}).encode("utf-8")
        request = urllib.request.Request(
            self.base_url,
            data=payload,
            headers={"Content-Type": "application/json", "X-API-KEY": self.api_key},
            method="POST",
        )
        raw = fetch(request, max_bytes=self.max_response_bytes, total_timeout=self.total_timeout)
        data = json.loads(raw.decode("utf-8"))
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
            for item in data.get("organic", [])
        ]


@dataclass
class WebSearchConfig:
    """provider: an already-constructed SearchProvider instance (e.g.
    TavilySearchProvider(api_key=...)). Same ownership split as
    SearchConfig/IngestConfig - this tool does not construct or manage
    the provider's lifecycle or credentials."""
    provider: SearchProvider


# The model controls num_results, and every result costs the caller's
# paid API quota - so it is clamped here, in one place, regardless of
# which provider is plugged in.
MAX_NUM_RESULTS = 20


def search_web(config: WebSearchConfig, query: str, num_results: int = 5) -> ToolResult:
    try:
        num_results = max(1, min(int(num_results), MAX_NUM_RESULTS))
    except (TypeError, ValueError):
        return ToolResult(success=False, error=f"num_results must be an integer, got {num_results!r}")
    try:
        results = config.provider.search(query, num_results=num_results)
        return ToolResult(success=True, result={"results": results, "count": len(results)})
    except urllib.error.URLError as e:
        return ToolResult(success=False, error=f"Network error reaching search provider: {e}")
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return ToolResult(success=False, error=f"Unexpected response shape from search provider: {type(e).__name__}: {e}")
    except Exception as e:
        # Defensive catch-all, same reasoning as search_documents():
        # a tool-calling loop should get a clean ToolResult back, never
        # an uncaught exception from a live network call it doesn't
        # control.
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def make_web_search_tool(config: WebSearchConfig) -> Tool:
    """Returns a single search_web Tool bound to this config's
    provider via closure, same binding pattern as
    search.make_search_tool() and ingest.make_ingest_tool()."""
    return Tool(
        name="search_web",
        description=(
            "Search the web for a query using whichever search provider "
            "is configured (e.g. Tavily, Serper). Returns titles, URLs, "
            "and snippets - not a generated answer. Use this for current "
            "information not likely to be in previously ingested documents."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=lambda query, num_results=5: search_web(config, query, num_results=num_results),
    )
