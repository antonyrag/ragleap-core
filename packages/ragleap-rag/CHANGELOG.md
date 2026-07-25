# Changelog

All notable changes to `ragleap-rag` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

- `docs`: Celery integration guide + runnable example ([#57](https://github.com/antonyrag/ragleap-core/pull/57))
- `test`: comprehensive pytest suite (67 tests) + CI integration — first automated testing this package has had ([#58](https://github.com/antonyrag/ragleap-core/pull/58))

## [0.5.6] - 2026-07

### Added
- Redis-backed distributed query embedding cache (`cache_backend="redis"`) — survives process restarts and is shared across multiple worker/Celery processes, unlike the in-memory cache. Requires the `[redis]` extra.
- `ingest_batch()` — concurrent mixed-type ingestion (file/url/image/audio/video in one call) with per-item partial-success results.
- Missing async ingest wrappers: `aingest_url`, `aingest_image`, `aingest_audio`, `aingest_video` — all 6 ingest methods now have async twins.

([#56](https://github.com/antonyrag/ragleap-core/pull/56))

## [0.5.5] - 2026-07

### Added
- Custom transcription provider support (`provider="custom"` + `transcribe_fn`) — bring your own transcription function instead of Whisper/Deepgram.

([#55](https://github.com/antonyrag/ragleap-core/pull/55))

## [0.5.4] - 2026-07

### Added
- Video ingestion (`ingest_video`) — extracts audio via ffmpeg, then transcribes it. Requires the ffmpeg binary on the system.

([#54](https://github.com/antonyrag/ragleap-core/pull/54))

## [0.5.3] - 2026-07

### Added
- Audio ingestion (`ingest_audio`) — pluggable transcription (Whisper or Deepgram).

([#53](https://github.com/antonyrag/ragleap-core/pull/53))

## [0.5.2] - 2026-07

### Added
- Image ingestion (`ingest_image`) — two modes: OCR (Tesseract, requires the `[ocr]` extra + system binary) and vision captioning (Gemini).

([#52](https://github.com/antonyrag/ragleap-core/pull/52))

## [0.5.1] - 2026-07

### Added
- Expanded document format support — 28 formats total (pptx, xlsx, xls, csv, tsv, json, yaml, xml, rtf, odt, ods, odp, html, zip, eml, epub, parquet, vtt, srt, and more). Requires the `[formats]` extra for the non-core formats.

### Fixed
- `__version__` in `src/ragleap/__init__.py` had not been bumped to match `pyproject.toml`'s `0.5.1` — caught via routine `git status` before publish, fixed same-day. No mismatched version reached PyPI.

([#50](https://github.com/antonyrag/ragleap-core/pull/50), [#51](https://github.com/antonyrag/ragleap-core/pull/51))

## [0.5.0] - 2026-07

### Added
- URL ingestion (`ingest_url`) — fetches a page and extracts clean readable text via trafilatura, stripping nav/ads/footers. Requires the `[web]` extra.

([#49](https://github.com/antonyrag/ragleap-core/pull/49))

## [0.4.7]

### Added
- Structured, chunk-level citations (`citations` field on `ask()`'s return value) — resolves ambiguity in `[Source N]` prompt labels: they always refer to a specific chunk, never a whole document.

([#48](https://github.com/antonyrag/ragleap-core/pull/48))

## [0.4.6]

### Added
- Content sanitization (`sanitize_text`) — strips null bytes, control characters, and invisible/zero-width Unicode before chunking. On by default (`sanitize=True`).
- Heuristic prompt-injection risk detection (`detect_injection_risk`) — logs a warning at ingest time on common trigger phrases. Pattern-based, not a guarantee; nothing is blocked automatically.

([#47](https://github.com/antonyrag/ragleap-core/pull/47))

## [0.4.5]

### Added
- Metadata filtering — `metadata_filter=` on `ask()`, JSONB containment query, GIN-indexed. The multi-tenant isolation mechanism.

### Known limitation (still open)
- `update_document()` does not forward the original document's metadata to the re-ingested version — silently resets to `{}` unless the caller passes `metadata=` again. Documented, not yet fixed.

([#46](https://github.com/antonyrag/ragleap-core/pull/46))

## [0.4.4]

### Added
- Document lifecycle: `list_documents()`, `delete_document()`, `update_document()`. `update_document()` is delete + re-ingest under the hood — chunk boundaries and embeddings are not preserved, and the document gets a new `document_id`.

([#45](https://github.com/antonyrag/ragleap-core/pull/45))

## [0.4.3]

### Added
- Async support: `aingest`, `aingest_text`, `aask`, `aask_stream` — wrap the sync implementation in `asyncio.to_thread()` so a blocking DB/embedding call doesn't stall an async web server's event loop.

([#44](https://github.com/antonyrag/ragleap-core/pull/44))

## [0.4.2]

### Added
- Query embedding caching — in-memory LRU (1000 entries by default), opt-out via `cache_enabled=False`. Caches embeddings only, never full answers (conversation memory means the same question can legitimately produce different answers depending on session history).

([#43](https://github.com/antonyrag/ragleap-core/pull/43))

## [0.4.1]

### Changed
- Connection pooling for all database access — previously every `ingest`/`ask`/memory operation opened a fresh Postgres connection. Automatic, no configuration needed.

([#41](https://github.com/antonyrag/ragleap-core/pull/41))

## [0.4.0]

### Added
- Cross-encoder reranking (`rerank=True` on `ask()`) — opt-in, requires the `[rerank]` extra (pulls in `sentence-transformers` + `torch`).

([#39](https://github.com/antonyrag/ragleap-core/pull/39), docs: [#40](https://github.com/antonyrag/ragleap-core/pull/40))

## [0.3.0]

### Added
- Persistent conversation memory — session-scoped, Postgres-backed. Pass `session_id=` to `ask()`/`ask_stream()` for multi-turn context; omit it for a stateless call (identical to prior behavior).

([#37](https://github.com/antonyrag/ragleap-core/pull/37), docs fix: [#38](https://github.com/antonyrag/ragleap-core/pull/38))

## [0.2.0]

### Added
- `EmbeddingConfig` — explicit, pluggable embedding provider configuration (Gemini, OpenAI).

### Breaking
- Replaced the old `embedder_api_key` constructor parameter with `EmbeddingConfig`. Anyone upgrading from 0.1.0 needs to change:
```python
  # Before (0.1.0)
  RagLeap(database_url=..., embedder_api_key="...")

  # After (0.2.0+)
  RagLeap(database_url=..., embedder=EmbeddingConfig(provider="gemini", api_key="..."))
```

([#36](https://github.com/antonyrag/ragleap-core/pull/36))

## [0.1.0] - Initial release

### Added
- `ragleap-rag` — standalone, pip-installable RAG package (Phase A of the `ragleap-core` open-source effort). Core loop: `ingest`/`ingest_text` → chunk → embed → store in Postgres+pgvector; `ask()` for grounded question answering. Gemini and Anthropic supported as generation providers, Gemini/OpenAI for embeddings.

([#35](https://github.com/antonyrag/ragleap-core/pull/35))

[Unreleased]: https://github.com/antonyrag/ragleap-core/compare/main...HEAD
