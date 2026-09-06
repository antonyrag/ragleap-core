# Changelog

All notable changes to `ragleap-vectorstores` are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.1] - 2026-09-05
### Fixed
- README's Usage section was missing a RedisBackend example (only
  Chroma/LanceDB were shown) - same category of gap as the v0.2.1
  missing-uv-add-lines fix, caught the same way: checking the real
  rendered PyPI page after publish rather than assuming the README
  was complete.
- pyproject.toml's keywords only listed generic terms (rag,
  vector-search, vector-database, ragleap) - added per-backend terms
  (chroma, chromadb, lancedb, redis, redisearch) plus embeddings and
  similarity-search for PyPI/search discoverability.

## [0.3.0] - 2026-09-05
### Added
- `RedisBackend` - third vector backend, via RediSearch/Redis Stack's
  HNSW vector index over a real Redis connection. Available via the
  `redis` optional extra (`pip install ragleap-vectorstores[redis]`).
  Unlike Chroma/LanceDB, this backend requires a real running server -
  plain Redis has no vector search; it must be Redis Stack, or plain
  Redis with the RediSearch module loaded. init_schema() checks
  MODULE LIST and raises a clear RuntimeError immediately if 'search'
  isn't present, rather than failing confusingly later at query time.
- KNOWN LIMITATION, documented honestly: RediSearch requires fields to
  be declared in the index schema up front, unlike Chroma's flexible
  `where=`. search_dense()'s metadata_filter only narrows results by
  `document_id` (a declared TAG field) - additional keys are accepted
  but ignored rather than raising, same 'don't claim a capability that
  isn't there' spirit as supports_sparse().
- `supports_sparse()` correctly reports `False` for Redis - RediSearch
  does support real full-text search via TextField/BM25, but that
  surface wasn't implemented or tested in this release.
### Fixed
- TAG field values (e.g. UUID document_ids containing hyphens) must be
  escaped before use in RediSearch query strings - live-verified that
  an un-escaped hyphenated document_id silently returns zero matches
  rather than erroring, since RediSearch parses hyphens as query syntax.
  Handled by _escape_tag() and covered by a dedicated regression test.

## [0.2.1] - 2026-08-31
### Fixed
- README's Install section was missing `uv add` variants for both
  extras (only `pip install` was shown) - caught by checking the real
  rendered PyPI project page after the v0.2.0 publish, not caught
  beforehand. Every other install example across this project's docs
  shows both pip and uv; this brings the package's own README (which
  becomes the permanent PyPI page content once published) in line.

## [0.2.0] - 2026-08-31
### Added
- `LanceDBBackend` - second vector backend, via LanceDB's embedded/local
  connection mode (a directory path, no server required). Available via
  the `lancedb` optional extra (`pip install ragleap-vectorstores[lancedb]`).
- Real upsert semantics via `merge_insert()` - re-inserting the same
  document_id/chunk_index updates the row in place rather than
  duplicating it.
- `supports_sparse()` correctly reports `False` for LanceDB - it does
  support full-text search via tantivy, but that surface wasn't
  implemented or tested in this release, so hybrid search honestly
  falls back to dense-only.

## [0.1.0] - 2026-08-29
### Added
- Initial package scaffold - pyproject.toml, package layout matching
  ragleap-graph's src/ragleap_vectorstores convention.
- `ChromaBackend` - first vector backend, implementing the full
  `VectorBackend` interface via chromadb's embedded PersistentClient
  (no server required). Available via the `chroma` optional extra
  (`pip install ragleap-vectorstores[chroma]`).
- `supports_sparse()` correctly reports `False` for Chroma - no native
  keyword/BM25 search as of chromadb 1.5.9, so hybrid search honestly
  falls back to dense-only rather than claiming unimplemented capability.
