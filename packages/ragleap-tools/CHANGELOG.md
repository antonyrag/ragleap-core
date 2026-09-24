# Changelog

All notable changes to `ragleap-tools` are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
