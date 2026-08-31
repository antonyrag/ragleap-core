# Changelog

All notable changes to `ragleap-vectorstores` are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
