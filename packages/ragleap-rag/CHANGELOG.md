# Changelog

All notable changes to `ragleap-rag` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

- `docs`: Celery integration guide + runnable example ([#57](https://github.com/antonyrag/ragleap-core/pull/57))
- `test`: comprehensive pytest suite (67 tests) + CI integration — first automated testing this package has had ([#58](https://github.com/antonyrag/ragleap-core/pull/58))

## [0.8.0]

### Added
- Structured/JSON output mode: `response_format=<JSON schema dict>` on `ask()`. Result gains `structured` (parsed object or `None`), `structured_valid` (bool), `structured_enforcement` (`"native"` or `"json_object_fallback"`), `structured_validation_method` (`"jsonschema"` or `"basic_type_check_only"`).
- New `ragleap.structured` module (`parse_and_validate()`, `parse_and_validate_object()`), new `[structured]` extra (`jsonschema>=4.0.0`) for real schema validation - without it, only a basic top-level type check runs, honestly flagged as such rather than claiming full validation.
- Gemini uses native `response_schema` constrained decoding. Anthropic uses forced tool-use (no OpenAI-style `response_format` exists for it) - a single tool whose `input_schema` is the desired shape, reading the parsed tool input directly. Both report `"native"` enforcement.
- OpenAI-compatible providers (OpenAI, Mistral, Together, Ollama) try strict `json_schema` mode first, honestly falling back to unconstrained `json_object` mode on failure (`"json_object_fallback"`) rather than silently claiming equal guarantees.
- **Live-verified this release** with a real Gemini API call (not mocked): correctly extracted structured city/country/population data from source context, passed real `jsonschema` validation. Anthropic/OpenAI-compatible paths are code-complete per each provider's public documentation but not live-verified against a real account this session.
- Not supported on `ask_stream()` - structured output needs the complete response before it's valid JSON; documented as a real gap, not silently unsupported.
- `_call_provider()`'s internal return contract changed from a 2-tuple to a 3-tuple (added enforcement mode) - a private-method change, not part of the public API, but noted for anyone who monkeypatched it directly (e.g. in tests).
- 11 new tests (139 -> 150 passing): `ragleap.structured` unit tests including a forced no-jsonschema-installed fallback path, plus `ask()` plumbing tests proving `response_format=` flows correctly end-to-end and real validation runs (not rubber-stamped).

### Known issue (not fixed this release)
- Discovered during live verification: the library's default Gemini model, `gemini-2.5-flash`, is now deprecated by Google (`404 NOT_FOUND` on new API calls) - affects any caller relying on the default rather than passing `model=` explicitly. Flagged as a follow-up, out of scope for this release.

## [0.7.0]

### Added
- Embedding provider expansion: Mistral, Together, Ollama, Cohere, and Voyage AI, alongside existing Gemini/OpenAI support.
- Mistral, Together, and Ollama reuse the existing `openai` package's client pointed at a custom `base_url` (all three expose OpenAI-compatible `/embeddings` endpoints) - no new dependency.
- Cohere and Voyage AI use `requests` (already a core dependency) directly, since their response shapes differ from OpenAI's.
- `ollama` is live-verified this release: fully local, no API key required, tested end-to-end (`embed_text()`, `embed_batch()`, and a full real ingest -> real FAISS retrieval integration test) via `nomic-embed-text`.
- `mistral`, `together`, `cohere`, and `voyage` are code-complete based on public API documentation but NOT live-verified against a real account - same caveat already attached to the Pinecone vector backend. Their default models/dimensions are best-effort until confirmed live.
- `together` requires explicit `model=` and `dimensions=` - no safe default exists across its many incompatible embedding models. Raises a clear error rather than guessing.
- Honest limitation documented for `cohere`: always uses `input_type="search_document"` since `embed_text()`/`embed_batch()` don't currently distinguish query vs. document embedding calls.
- 16 new tests: live Ollama tests (skipped automatically if Ollama isn't running, so CI never fails on its absence) plus config-resolution/error-handling tests for the four unverified providers (123 -> 139 passing).

## [0.6.4]

### Added
- Cost-First RAG: `ask()` now returns a `cost` field (`cost_usd`, `cumulative_cost_usd`, `pricing_available`) computed from real provider-reported token usage. New `ragleap.cost` module (`compute_cost()`, `CostTracker`).
- Built-in seed pricing table for Gemini, Anthropic, and OpenAI, verified via live web search on 2026-07-28 (not from training-data memory, since pricing changes fast). `pricing_table=` on `RagLeap.__init__()` merges with/overrides the seed table — user-supplied entries always win. Unknown provider/model combinations return `cost_usd: None`, never a guessed number.
- Budget-triggered fallback: `budget_usd_per_month=` + `budget_fallback=` on `RagLeap.__init__()`. Once cumulative spend crosses the budget, subsequent `ask()`/`ask_stream()` calls use `budget_fallback` for that call only via a new non-mutating `override_provider=` param on `GenerationService.generate_answer()`/`generate_answer_stream()` — the shared instance's own primary/fallback chain is never touched, so concurrent calls aren't affected by one request's fallback decision.
- `generate_answer()`'s return dict gained a `model_used` field (alongside the existing `provider_used`) - needed to look up pricing, and a genuinely useful addition on its own.
- `ask_stream()` never reports a real `cost_usd` (streaming has no token usage data - see the Streaming section), but `override_provider` still applies for budget-triggered fallback if configured.
- 17 new tests, including a real end-to-end proof that budget-triggered fallback switches `provider_used` on the second call once the first call's real cost crosses the budget.

## [0.6.3]

### Added
- Observability hooks: `on_ingest=`/`on_query=`/`on_answer=` on `RagLeap.__init__()` - lightweight, fire-and-forget event emission, not a dashboard or storage layer. Each is a list of `(event: dict) -> None` callables.
- `on_ingest` fires after successful ingestion with document_id/filename/chunks_stored/chunks_attempted.
- `on_query` fires after retrieval (before generation) with query/hybrid/rerank/top_k/chunks_retrieved/streaming.
- `on_answer` fires after generation on both `ask()` (provider_used/usage/chunks_sent/guardrail_blocked) and `ask_stream()` (answer_length, since usage isn't available for streaming) - every event includes `streaming: bool`.
- A hook that raises is caught, logged as a warning, and swallowed - never breaks the actual ingest/ask operation. New `ragleap.observability` module (`fire_event()`).
- 7 new tests, including explicit coverage that a broken hook does not break ingestion or asking.

## [0.6.2]

### Added
- `rag.evaluate(test_cases)` - a lightweight, deterministic evaluation utility. Reports retrieval hit rate, keyword coverage, and citation groundedness against a labeled test set. Explicitly NOT an LLM-as-judge framework (no faithfulness/relevancy scoring like Ragas) - that requires careful judge-prompt calibration and is planned as a separate, dedicated tool. This is a fast, free, repeatable sanity check for catching regressions in your own retrieval/generation setup.
- New `ragleap.evaluation` module: `evaluate()` and `evaluate_case()`.
- 8 new tests, including using the fake test generator's real prompt-echo behavior to create genuinely checkable keyword overlap (not coincidental passes).

## [0.6.1]

### Added
- Guardrail hooks: `input_guardrails=`/`output_guardrails=` on `RagLeap.__init__()` - user-supplied validation callbacks that extend (not replace) the existing sanitization/injection-risk detection. Each guardrail is `(text: str) -> str`, or raises `GuardrailViolation` to reject content.
- `input_guardrails` run during `ingest_text()`, after sanitization - a violation aborts ingestion with nothing stored.
- `output_guardrails` run on `ask()`'s answer - a violation replaces the answer with a refusal message and sets `answer["guardrail_blocked"] = True`.
- `ask_stream()` support with an honestly-documented limitation: output guardrails can only run after the full answer is assembled, but tokens are already yielded to the caller by then - a violation during streaming is logged as a warning, not enforced. Use `ask()` instead if blocking bad output before the user sees it matters.
- 8 new tests covering modification, rejection, ordering, and the ask()/ask_stream() enforcement difference.

## [0.6.0]

### Added
- Pluggable vector storage backends via `vector_backend=` on `RagLeap.__init__()`. Vector storage is now decoupled from conversation memory (which always uses Postgres regardless of vector backend choice, since memory is a separate concern).
- `ragleap.vectorstores.VectorBackend` — the abstract interface any backend implements (`init_schema`, `insert_document`, `insert_chunk`, `search_dense`, `list_documents`, `delete_document`, `get_document_filename`, optionally `search_sparse`/`search_hybrid`/`supports_sparse`).
- `PgVectorBackend` — the default, a refactor (not a rewrite) of the existing proven Postgres/pgvector logic. Zero behavior change for existing users; verified via the full existing test suite passing unmodified (73/73) after the refactor.
- `FAISSBackend` — new, local, in-process, no API key required. Requires the `[faiss]` extra. No native full-text search (`supports_sparse()` returns `False`; `ask(hybrid=True)` gracefully degrades to dense-only). Metadata filtering is a post-filter over a SQLite sidecar, not an indexed query. Optional `persist_directory=` for data that survives process restarts — verified live across separate backend instances pointed at the same directory, not just in-process. 10 new tests, all live against a real FAISS index (no mocking of the backend itself).

### Changed
- Internal: `RagLeap._retriever` (the old `VectorRetrievalService`) removed in favor of `RagLeap._vector_backend`. This is a private-attribute rename — anyone reaching into `rag._retriever` directly (not part of the public API) needs to update to `rag._vector_backend` with its new method names (`search_dense`/`search_sparse`/`search_hybrid` instead of `search_similar_chunks`/`search_sparse_chunks`/`search_hybrid_chunks`).
- `schema.py` split into independent core schema (documents/chunks, backend-specific) and memory schema (conversations/conversation_messages, always Postgres) - `init_schema()`/`get_schema_sql()` remain as backward-compatible combined wrappers for anyone calling the module directly.

## [0.5.8]

### Changed
- Reranking now runs on ONNX Runtime (CPU only) instead of torch/sentence-transformers — the `[rerank]` extra no longer pulls in a 2GB+ torch+CUDA install for what is, at this model size, pure CPU inference. A quantized cross-encoder (~23MB, `Xenova/ms-marco-MiniLM-L-6-v2`) downloads once via `huggingface_hub` and is cached locally.

### Breaking (opt-in extra only)
- `RerankerService.__init__()`'s `model_name=` param is now `model_repo=` (a Hugging Face repo id, not a sentence-transformers model name). Only affects callers who passed a custom reranking model explicitly — the default behavior (no argument) is unaffected.

## [0.5.7]

### Fixed
- `ask_stream()` (and `aask_stream()`) were missing `rerank=` and `metadata_filter=` params that `ask()` already had — a real, previously-flagged API inconsistency. Both are now supported identically across the sync/async and streaming/non-streaming variants. Regression-covered by 4 new tests.

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
