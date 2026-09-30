"""
ragleap_tools.github_search

Searches GitHub repositories via the real GitHub REST API
(/search/repositories). Not a SearchProvider implementation - GitHub's
API has a different shape (GET + query params, not POST + JSON body)
and a different auth model (a token is optional, not required) from
Tavily/Serper. See docs/design/web-search-tool.md for the full
rationale.

Uses stdlib urllib.request, same as web_search.py - no new dependency.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ragleap_tools.base import Tool, ToolResult

BASE_URL = "https://api.github.com/search/repositories"

# GitHub's API requires a real User-Agent header and rejects requests
# without one - not optional the way it is for most REST APIs.
USER_AGENT = "ragleap-tools/github-search"

MAX_NUM_RESULTS = 20


@dataclass
class GitHubSearchConfig:
    """token: optional - GitHub allows unauthenticated repository
    search at a real, lower rate limit (60 requests/hour per IP,
    documented by GitHub itself). No env var fallback: if a token is
    wanted, pass it explicitly, same BYOK stance as every other tool
    in this package."""
    token: Optional[str] = None


def search_github_repositories(
    config: GitHubSearchConfig,
    query: str,
    num_results: int = 5,
    sort: Optional[str] = None,
) -> ToolResult:
    try:
        num_results = max(1, min(int(num_results), MAX_NUM_RESULTS))
    except (TypeError, ValueError):
        return ToolResult(success=False, error=f"num_results must be an integer, got {num_results!r}")

    params = {"q": query, "per_page": num_results}
    if sort:
        params["sort"] = sort
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"

    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        results = [
            {
                "full_name": item.get("full_name", ""),
                "url": item.get("html_url", ""),
                "description": item.get("description") or "",
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language") or "",
            }
            for item in data.get("items", [])
        ]
        return ToolResult(success=True, result={"results": results, "count": len(results)})
    except urllib.error.HTTPError as e:
        # GitHub returns real, informative error bodies (rate limit
        # messages, validation errors on a malformed query) - surface
        # the body text, not just the status code.
        body = e.read().decode("utf-8", errors="replace")
        return ToolResult(success=False, error=f"GitHub API error {e.code}: {body}")
    except urllib.error.URLError as e:
        return ToolResult(success=False, error=f"Network error reaching GitHub: {e}")
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return ToolResult(success=False, error=f"Unexpected response shape from GitHub: {type(e).__name__}: {e}")
    except Exception as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def make_github_search_tool(config: GitHubSearchConfig) -> Tool:
    """Returns a single search_github_repositories Tool bound to this
    config's token via closure, same binding pattern as every other
    tool in this package."""
    return Tool(
        name="search_github_repositories",
        description=(
            "Search GitHub for repositories matching a query. Supports "
            "GitHub's real search qualifiers (e.g. 'language:python', "
            "'stars:>100', 'topic:llm') in the query string, same as "
            "GitHub's own search UI. Works without a token at a lower "
            "rate limit; pass one for higher limits."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, optionally with GitHub qualifiers (language:, stars:, topic:, etc.).",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return.",
                    "default": 5,
                },
                "sort": {
                    "type": "string",
                    "description": "Sort by 'stars', 'forks', or 'updated'. Omit for best-match relevance.",
                },
            },
            "required": ["query"],
        },
        handler=lambda query, num_results=5, sort=None: search_github_repositories(
            config, query, num_results=num_results, sort=sort
        ),
    )
