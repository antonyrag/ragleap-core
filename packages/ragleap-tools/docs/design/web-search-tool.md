# Web search tool — pluggable provider design

## Problem

CrewAI ships web search as hardcoded, per-provider tools
(`SerperDevTool`, `ExaSearchTool`). This ecosystem's own BYOK
philosophy (no vendor lock-in, bring your own keys) means a single
hardcoded provider is the wrong shape - the same reasoning already
applied to `ragleap-rag`'s embedding/generation providers.

## Design

A `SearchProvider` abstract base class (`search(query, num_results) ->
List[SearchResult]`), with reference implementations for two real
providers with meaningfully different API shapes:

- `TavilySearchProvider` - purpose-built for LLM/RAG use cases, returns
  clean summarized snippets already.
- `SerperSearchProvider` - Google Search results via a proxy API, more
  raw (titles/links/snippets), closer to what a user would see on
  Google directly.

Each provider requires `api_key: str` at construction - explicit,
required, no env var fallback, no hardcoded default. Matches
`ragleap-rag`'s own stated philosophy: "the library just always asks
you to know and specify your model" (from its README's LLM providers
section) - the same reasoning applies to search API keys.

`WebSearchConfig` holds a `provider: SearchProvider` instance (not a
provider name string) - the caller constructs whichever real provider
they want and passes it in, same as `SearchConfig.rag` and
`IngestConfig.rag` already do for `ragleap-rag` instances. No provider
registry, no string-based dispatch - explicit construction only.

## Dependencies

Uses stdlib `urllib.request`, not a new `requests`/`httpx` dependency.
`ragleap-tools` has zero required dependencies today (`dependencies =
[]` in pyproject.toml) - the package's own docstring calls itself
"dependency-light." Adding a required HTTP library just for one
optional tool would be a real regression. Both Tavily's and Serper's
APIs are simple JSON POST requests - `urllib.request` handles this
without added complexity.

## Error handling

Network errors (`urllib.error.URLError`), non-200 responses, and
malformed JSON are all caught and returned as a `ToolResult(success=
False, error=...)` - never raised, matching every other tool in this
package (per `base.py`'s own `ToolResult` docstring: "handlers should
never raise for expected failure modes").

## Result shape

Returns a list of `{"title": str, "url": str, "snippet": str}` dicts -
a normalized shape both providers can produce, unlike `search_documents`
which deliberately returns `ragleap-rag`'s chunks unmodified. Web search
results from different providers have genuinely different native
shapes (Tavily's "content" vs Serper's "snippet", etc.) with no
existing shared consumer depending on the raw shape - normalizing here
is the right call, unlike the ragleap-rag chunk case where an existing
format was worth preserving exactly.

## What this doesn't do

Does not include response caching, rate limiting, or result
deduplication across providers - out of scope for a first version.
Each provider call is a live, uncached network request.

## Result-count clamp

`num_results` is model-controlled and every result costs the caller's
paid API quota, so `search_web()` clamps it to 1-20 regardless of which
provider is configured, and rejects non-integer values without ever
calling the provider. The clamp lives in `search_web()`, not in the
individual providers, so a custom `SearchProvider` gets it for free.

## Verification status

Request shapes were checked against each provider's current public
documentation and independent implementations, not against a live
account (no API keys were available). Tavily: `POST
https://api.tavily.com/search`, `Authorization: Bearer <key>`, body
`{query, max_results}` - an earlier draft put the key in the body, which
is not what the current docs show, and was corrected. Serper: `POST
https://google.serper.dev/search`, `X-API-KEY` header, body `{q, num}`,
results under `organic[]` (title/link/snippet). Tavily's response
field names (`results[].title/url/content`) come from prior knowledge
of its schema and were not re-confirmed in the pages checked. Neither
provider has been called live - treat both as best-effort until
confirmed by someone with a real key, the same honest standard already
applied to ragleap-rag's unverified providers.

## Untrusted content

Search results are text from arbitrary third-party pages flowing into
the model's context. A hostile page can contain instructions aimed at
the model (prompt injection). This tool does not sanitize or screen
results - it returns titles, URLs and snippets as the provider gives
them. Callers wiring this into an agent loop should treat results as
untrusted input.

## GitHub repository search - a second, related provider-style tool

Not a `SearchProvider` implementation - GitHub's search API has a
meaningfully different shape (GET with query params, not POST with a
JSON body) and a meaningfully different auth model (a token is
optional, unlike Tavily/Serper where a key is required). Forcing it
into the `SearchProvider` interface would mean either lying about the
optional-token capability or adding an awkward `Optional[str]`
special case to an interface every other implementation treats as
required. A separate `GitHubSearchConfig`/`search_github_repositories`
pair, following the same overall pattern (stdlib `urllib.request`,
`ToolResult` never-raise, `Tool`/config-binding shape), is more honest
than a forced abstraction.

`token: Optional[str] = None` - GitHub allows unauthenticated repository
search at a real, lower rate limit than its core API (a live
`/rate_limit` check on 2026-10-01 showed 10 for the search resource and
60 for core, unauthenticated; an earlier version of this doc wrongly
gave 60 requests/hour for search). No fallback to reading an env var - if a token is
wanted, the caller passes it explicitly, same BYOK stance as everywhere
else in this package.

GitHub's API requires a `User-Agent` header on every request and
rejects requests without one - a real, easy-to-miss requirement, not
optional the way it is for most REST APIs. Set unconditionally.

Scoped to repository search only (`/search/repositories`), not code or
issue search - one tool doing one clear thing, matching this package's
existing `search_documents`/`search_web` granularity rather than one
tool trying to cover three different GitHub search endpoints with
different result shapes.
