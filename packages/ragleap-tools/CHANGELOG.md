# Changelog

All notable changes to `ragleap-tools` are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.0] - 2026-09-29

### Added

- `search_github_repositories` tool (`GitHubSearchConfig`,
  `make_github_search_tool`) via the real GitHub REST API
  (`/search/repositories`). Unlike `search_web`'s providers, a token is
  optional - GitHub allows unauthenticated search at a real, lower rate
  limit, so this is not forced into the `SearchProvider` interface (see
  `docs/design/web-search-tool.md` for the full reasoning). Sets a
  real `User-Agent` header, which GitHub's API requires and rejects
  requests without. Standard library only - no new dependency.
  `num_results` clamped to 1-20, same reasoning as `search_web`.

### Verified

- 100 tests passing (was 85). 15 new: request-building tests mock
  `urllib.request.urlopen` and assert on the real query string and
  headers, including that no `Authorization` header is sent without a
  token and a `Bearer` header is sent with one.

## [0.2.0] - 2026-09-28

### Added

- `search_web` tool (`WebSearchConfig`, `make_web_search_tool`) with a
  pluggable `SearchProvider` abstraction and two reference providers,
  `TavilySearchProvider` and `SerperSearchProvider`. Bring-your-own-key:
  `api_key` is required at construction, with no environment-variable
  fallback and no default provider. Standard library only
  (`urllib.request`) - `ragleap-tools` still has zero required
  dependencies. Results are normalized to `{"title", "url", "snippet"}`.
- `num_results` is model-controlled and costs the caller's paid API
  quota, so `search_web()` clamps it to 1-20 (in the tool, not the
  providers, so custom providers get it too) and rejects non-integer
  values without calling the provider. See
  `docs/design/web-search-tool.md`.

### Changed

- Web search is no longer listed as out of scope. Code execution, HTTP
  fetch and database/business-system connectors remain deferred.

### Known limitations

- Neither provider has been called against a live account. Request
  shapes were checked against each provider's current public docs; an
  earlier draft sent Tavily's key in the request body, which is not what
  its current docs show, and was corrected to a Bearer header before
  release. Treat both as best-effort until confirmed live.
- Search results are untrusted third-party text; nothing screens them
  for prompt injection.
- No caching, rate limiting or result deduplication.

### Verified

- 85 tests passing (was 69). 16 new: the provider request-building
  tests mock `urllib.request.urlopen` so each provider's real payload
  and headers are exercised (including that Tavily's key is in the
  header and absent from the body), plus the `num_results` clamp and
  the package exports.

## [0.1.1] - 2026-09-24

### Added

- `search_documents` tool (`SearchConfig`, `make_search_tool`) wrapping
  `ragleap-rag`'s already-tested `retrieve()` for hybrid vector+keyword
  search over previously ingested documents. Chunk dicts are returned
  unmodified - this tool doesn't assume `ragleap-rag`'s exact field
  set. Optional `filename=` parameter scopes search to a single
  document.

### Fixed

- `ingest_document` now passes `metadata={"filename": filename}` to
  `ingest_text()`. Previously passed no metadata at all, which
  silently made every document ingested through this tool unfilterable
  by anything using `metadata_filter` (it matches against the metadata
  dict, not the `document_id`/`document_name` columns) - including the
  new `search_documents`' `filename=` parameter, which depends on this.
  Backward compatible: existing callers gain a capability, nothing
  about the tool's signature or return shape changed.

### Verified

- 69 tests, all passing (was 51 in v0.1.0). New coverage: 8 tests for
  `search_documents` (including the `filename=` metadata-filter path,
  asserted against the fake's actually-recorded `metadata_filter`
  value, not just call-succeeded), 6 tests for `ingest_document`
  (a real gap backfilled - v0.1.0 shipped this tool with zero direct
  test coverage; the metadata-threading regression this release fixes
  is exactly the kind of bug that gap would have hidden).

## [0.1.0] - 2026-09-16

### Added

- Initial release. `Tool`/`ToolResult` base abstraction with OpenAI
  and Gemini function-calling schema generation. Deliberately does not
  own a tool-calling execution loop - that's `ragleap-agents`' scope,
  per the project roadmap's own split.
- 12 stateless tools: calculator (safe AST-based expression
  evaluation, never `eval()`/`exec()`), `get_current_datetime`,
  `add_to_date`, `date_difference`, `convert_length`,
  `convert_weight`, `convert_temperature`, `parse_json`, `parse_csv`,
  `regex_extract`, `word_count`, `text_case_transform`.
- 3 sandboxed file-op tools (`read_file`, `write_file`, `list_files`)
  via `FileOpsConfig(root_dir=...)` - confined entirely to a
  caller-specified root directory. Path resolution follows symlinks
  before checking containment, so symlink-based sandbox escapes are
  rejected, not just naive `../` string checking.
- 1 optional ingestion tool (`make_ingest_tool`, needs the `ingest`
  extra: `pip install ragleap-tools[ingest]`) wrapping `ragleap-rag`'s
  already-tested `ingest_text()` - no new ingestion logic.
- Explicitly out of scope for this release: code execution, web
  search, HTTP fetch, and database/business-system connectors - each
  documented in the README as needing its own security-focused design
  pass rather than a rushed inclusion.

### Verified

- 51 tests, all passing. Includes real security verification, not
  just documentation: the calculator's AST whitelist is tested against
  real code-injection attempts (`__import__`, attribute access, list
  comprehensions, multi-statement injection - all correctly rejected),
  and file ops' sandboxing is tested against real path-traversal
  attempts AND a real symlink-escape attempt (a file outside the
  sandbox, symlinked from inside it - correctly rejected).
