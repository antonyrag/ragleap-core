# Bounded HTTP for the network providers (ragleap-tools v0.4.1)

## Problem

The four network call sites (Tavily, Serper, GitHub search, and the shared
vision `_post_json` for Gemini and Anthropic) used `urlopen(..., timeout=N)`
followed by an unbounded `response.read()`. urllib's timeout applies to each
individual socket operation, not to the whole request, so a server that sends
a few bytes every few seconds never trips it, and a huge body is read into
memory in full. Either holds a caller's tool-calling loop, and its memory,
for as long as the server likes. The same weakness was reproduced and fixed
in `ragleap-integrations` v0.1.0 (a deadline checked between chunks is not a
deadline).

## Design

One private module, `ragleap_tools/_http.py`, with one function, `fetch()`,
used by all four sites. It keeps `urllib.request.urlopen` as the seam (looked
up at call time), so existing tests that patch it keep working.

- Hard size cap: `max_response_bytes` (default 1 MiB). Declared
  `Content-Length` over the cap is rejected before reading; otherwise the
  body is read in chunks (`read1`) and stops at the cap. A body shorter than
  its declared length is an error ("response was truncated").
- Hard total deadline: `total_timeout` (default 20 s; 90 s for the vision
  providers). The request runs in a worker thread and the caller gets control
  back at the deadline.
- HTTP error bodies are capped at 16,384 bytes and stay readable with
  `.read()`, so GitHub's informative error text still reaches the caller.
- Both failures are `urllib.error.URLError` subclasses, so every existing
  `except URLError` handler reports them as a failed `ToolResult`.
- New optional, validated fields (`max_response_bytes`, `total_timeout`) on
  the providers and `GitHubSearchConfig`; existing code is unaffected.
- Per-operation socket timeouts are unchanged (15 s; 60 s for vision).

Rejected alternatives: sharing the `ragleap-integrations` transport (the
dependency points the other way, and these providers call fixed, owner
configured hosts, so address pinning is not needed); switching to
`http.client` (would break every test that patches `urlopen`).

## Limitations

- Python cannot kill a thread. After the deadline the worker is told to stop
  and its socket is shut down on a best-effort basis; that uses private
  attributes of urllib's response object. If it stops working, the worker
  exits within one per-operation timeout. Control always returns on time.
- DNS resolution is not covered by the per-operation timeout.
- Responses over the cap now fail where they used to succeed.

## Verification status

- Verified: 67 new tests against a real local HTTP server (slow-drip body,
  stalled body, a server that never answers, oversize with and without
  Content-Length, chunked, truncated, huge error body) plus the 133 existing
  tests unchanged; Python 3.10.12 and 3.12.3. Mutation-tested: 38 deliberate
  breaks, all caught.
- Live, on the new transport: Gemini vision returned the expected answer for
  a generated red image (Python 3.10.12, 2026-10-09); unauthenticated GitHub
  search worked, and the size cap, the deadline and a real HTTP 422 error body
  were exercised against api.github.com.
- Not verified live: Anthropic vision, Tavily, Serper, authenticated GitHub.
