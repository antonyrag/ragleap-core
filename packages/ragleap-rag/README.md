# ragleap-rag

**A fast, honest, self-hosted RAG engine.** Hybrid dense+sparse retrieval,
real streaming, automatic provider fallback, and actual token usage
numbers — not estimates. Bring your own API keys; nothing is routed
through us.

```bash
pip install ragleap-rag[gemini]
# or
uv add ragleap-rag[gemini]
```

## Quickstart

You'll need two things: a PostgreSQL database with the
[pgvector](https://github.com/pgvector/pgvector) extension, and a free
[Gemini API key](https://aistudio.google.com/apikey) (used for embeddings).

```python
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

rag = RagLeap(
    database_url="postgresql://user:pass@localhost/mydb",
    embedder=EmbeddingConfig(provider="gemini", api_key="your-gemini-key"),
    primary=ProviderConfig(provider="gemini", api_key="your-gemini-key"),
)
rag.init_schema()  # one-time, idempotent — safe to call every run

rag.ingest_text("handbook.txt", "Employees get unlimited PTO and a $500/year learning budget.")

answer = rag.ask("How much PTO do employees get?")
print(answer["answer"])
```
Employees get unlimited PTO. (Source 1)

That's the whole loop: ingest text (or a `.txt`/`.pdf`/`.docx` file via
`rag.ingest(filename, raw_bytes)`), then ask questions grounded in it.

## The three things that matter

**Retrieval** is hybrid by default — dense (pgvector cosine similarity)
and sparse (Postgres full-text search) results are combined via
Reciprocal Rank Fusion, so both semantic matches and exact keyword/
identifier matches get found. Pass `hybrid=False` to `rag.ask(...)` for
dense-only retrieval (cheaper — one query instead of two).

**Generation** accepts `temperature`, `system_prompt`, and `max_tokens`
as real per-call arguments — build your own agent behavior on top of
retrieval without forking the library:
```python
answer = rag.ask(
    "Summarize the handbook",
    temperature=0.1,
    system_prompt="Answer in exactly one sentence.",
    max_tokens=100,
)
```

**Reliability** — configure a fallback chain so a rate limit, outage, or
bad key on your primary provider doesn't mean a failed request:
```python
rag = RagLeap(
    database_url="...",
    embedder=EmbeddingConfig(provider="gemini", api_key="..."),
    primary=ProviderConfig(provider="gemini", api_key="..."),
    fallbacks=[ProviderConfig(provider="groq", api_key="...", model="llama-3.3-70b-versatile")],
)
```
Every `ask()` response tells you which provider actually answered
(`answer["provider_used"]`) and exactly how many tokens it cost
(`answer["usage"]`) — real numbers pulled from the provider's own
response, not an estimate.

## Streaming

```python
for piece in rag.ask_stream("What SDKs are supported?"):
    print(piece, end="", flush=True)
```
Real per-provider streaming — Gemini, Anthropic, and any OpenAI-compatible
endpoint each have different streaming APIs; all three are implemented
properly, not stubbed.

## Async support

async equivalents exist for every method that touches the database or an API: aingest, aingest_text, aask, aask_stream. Use these inside an async web server (FastAPI, etc.) so a slow embedding call or LLM response does not block the event loop.

```python
result = await rag.aingest_text("handbook.txt", "...")
answer = await rag.aask("How much PTO do employees get?")
async for piece in rag.aask_stream("What SDKs are supported?"):
    print(piece, end="", flush=True)
```

Honest note: these wrap the existing, tested sync implementation in a worker thread (asyncio.to_thread) rather than using natively async database/HTTP clients end to end. This still avoids blocking the event loop and works correctly under concurrent load - confirmed via a live test running 3 aask() calls concurrently - but it is not the same as a from-scratch async rewrite using asyncpg and async HTTP clients throughout. A fully native async implementation may follow in a future release if there is real demand for it.

## Conversation memory

Pass session_id to ask() or ask_stream() to get persistent, multi-turn memory. Prior turns in that session are automatically injected as context. Omit it and every call is fully stateless, exactly as before (no breaking change).

```python
session = "support-chat-42"

rag.ask("What is the CEO name", session_id=session)
rag.ask("What country is he based in", session_id=session)
```

Memory is Postgres-backed (its own conversations/conversation_messages tables, created by init_schema()). It survives restarts and works across processes, not just in-memory for a single script run.

```python
rag.get_history(session)
rag.clear_session(session)
```

By default the last 10 messages are included per call (max_history_messages, no token-aware trimming yet).

## Reranking

Pass rerank=True to ask() for cross-encoder reranking. The initial hybrid search retrieves a wider candidate pool, then a cross-encoder scores each (query, chunk) pair jointly, reordering results by genuine relevance rather than the initial retrieval score alone. Off by default (extra latency, extra dependency).

```python
answer = rag.ask("What is the exact pricing?", rerank=True)
```

Requires the rerank extra:

```bash
pip install ragleap-rag[rerank]
```

The cross-encoder model (cross-encoder/ms-marco-MiniLM-L-6-v2 by default) loads lazily on the first rerank=True call, not at RagLeap construction time. Note: sentence-transformers depends on torch, which may pull in CUDA libraries even for CPU-only use — if you only need CPU inference, consider installing a CPU-only torch build first.

Not currently available on ask_stream().

## Document lifecycle

list_documents(), delete_document(), and update_document() manage previously ingested content.

```python
docs = rag.list_documents(limit=20)
for d in docs:
    print(d["filename"], d["chunk_count"], "chunks")

rag.delete_document(docs[0]["document_id"])

# update_document is delete + re-ingest under the hood - the document
# gets a new document_id, old chunks and embeddings are not preserved
result = rag.update_document(some_document_id, "new content here")
```

## Metadata & filtering

Attach arbitrary JSON metadata to a document at ingest time, then restrict retrieval to matching chunks with metadata_filter on ask() - the basis for multi-tenant isolation, date-range filtering, or any other tagging scheme.

```python
rag.ingest_text("acme_handbook.txt", "...", metadata={"tenant": "acme"})
rag.ingest_text("globex_handbook.txt", "...", metadata={"tenant": "globex"})

# Only retrieves chunks whose metadata contains {"tenant": "acme"}
answer = rag.ask("What is our PTO policy?", metadata_filter={"tenant": "acme"})
```

Filtering uses Postgres JSONB containment (metadata @> filter), backed by a GIN index - so it scales, and metadata can hold any JSON-serializable structure, not just flat tenant IDs. metadata is also returned by list_documents().

Known limitation: update_document() does not currently preserve the original document's metadata - re-ingesting content via update_document() resets metadata to empty unless you pass it again yourself. Worth fixing in a follow-up if this trips anyone up.

## Content sanitization

ingest_text() sanitizes and screens content by default (sanitize=True, warn_on_injection_risk=True) - both can be disabled per call if you are already sanitizing upstream.

```python
# Default: sanitizes control characters and warns on suspicious patterns
rag.ingest_text("doc.txt", text)

# Opt out if you handle this yourself
rag.ingest_text("doc.txt", text, sanitize=False, warn_on_injection_risk=False)
```

Sanitization strips null bytes, control characters, and invisible/zero-width Unicode characters - a documented technique for hiding instructions inside text that looks normal to a human reviewer.

Injection-risk detection is heuristic pattern matching against a fixed list of common trigger phrases ("ignore previous instructions", "reveal your system prompt", etc). It logs a warning and does NOT block ingestion. Honest limitation: this is pattern matching, not semantic understanding - prompt injection via retrieved content is an open research problem, and a sufficiently motivated attacker can rephrase around any fixed pattern list. Treat a warning as a signal to review, not a guarantee of safety, and treat the absence of a warning as "nothing matched", not "this content is safe."

## Citations

Every ask() response includes a citations field - a structured, chunk-level breakdown that resolves a real ambiguity: a citation like "(Source 1)" in an answer could mean a whole document or one specific passage within it. It always means the latter.

```python
answer = rag.ask("What is our refund policy?")
print(answer["answer"])

for c in answer["citations"]:
    print(c["source_number"], c["document_name"], "chunk", c["chunk_index"], "-", c["text_preview"])
```

Each citation includes source_number (matching the [Source N] label the model was given in its prompt), document_name, document_id, chunk_id, chunk_index, and a text_preview of that specific chunk - enough to verify exactly which passage backs a claim, which matters for audit or compliance use cases. The existing sources field (a deduped list of document names) is unchanged for backward compatibility.

## URL ingestion

ingest_url() fetches a web page and extracts clean, readable text - stripping navigation, ads, and other boilerplate via trafilatura - rather than ingesting raw HTML markup. Requires the web extra.

```bash
pip install ragleap-rag[web]
```

```python
result = rag.ingest_url("https://example.com/blog/some-article")
answer = rag.ask("What does the article say about X?")
```

The URL itself is stored as the document_name, so citations point back to the original page. Metadata works the same as ingest_text() - pass metadata= to tag the ingested content.

## Supported file formats

rag.ingest(filename, raw_bytes) supports 28 formats via file extension, dispatched automatically. Core formats (txt, pdf, docx, md) work with the base install; everything else requires the formats extra.

```bash
pip install ragleap-rag[formats]
```

**Office & documents**: pdf, docx, pptx, odt, ods, odp, rtf
**Spreadsheets & tabular**: xlsx, xls, csv, tsv, parquet
**Structured data**: json, yaml, xml, xsl, xslt
**Markup & web**: html, htm, md
**Archives & email**: zip (recurses into supported files inside), eml
**Books & media metadata**: epub, vtt, srt (subtitle cue numbers and timestamps are stripped, spoken text kept)
**Plain text**: txt, sql

**Not supported**: legacy binary .doc and .ppt (pre-2007 Office formats) - no reliable pure-Python parser exists for these. Convert to the modern equivalent first, e.g. via LibreOffice headless: soffice --headless --convert-to docx yourfile.doc

```python
with open("report.xlsx", "rb") as f:
    rag.ingest("report.xlsx", f.read())
```

## Image ingestion

ingest_image(filename, raw_bytes, mode=...) supports two different techniques for two different kinds of images.

mode="ocr" (default) reads literal visible text - scanned documents, screenshots, photos of text. Requires the ocr extra AND the Tesseract binary installed on the system (not pip-installable - e.g. apt install tesseract-ocr on Debian/Ubuntu).

mode="caption" describes an image's contents using a vision-capable model instead - for photos, diagrams, or charts with no readable text. Currently requires Gemini configured as the primary or a fallback provider; no extra install needed since it reuses the existing generation client.

```bash
pip install ragleap-rag[ocr]
```

```python
# Scanned document or screenshot
rag.ingest_image("receipt.png", raw_bytes, mode="ocr")

# Photo, chart, or diagram with no text
rag.ingest_image("product_photo.jpg", raw_bytes, mode="caption")
```

## Audio ingestion

ingest_audio(filename, raw_bytes, transcriber=None) transcribes audio and ingests the result. Defaults to OpenAI's hosted Whisper API using OPENAI_API_KEY from the environment; pass a TranscriptionConfig to choose a different provider or add options.

```python
from ragleap import TranscriptionConfig

# Default: Whisper via OpenAI
rag.ingest_audio("meeting.mp3", raw_bytes)

# Explicit config, with a vocabulary hint and language
config = TranscriptionConfig(provider="whisper", language="en", prompt="RagLeap, pgvector, Gemini")
rag.ingest_audio("meeting.mp3", raw_bytes, transcriber=config)

# Deepgram instead
config = TranscriptionConfig(provider="deepgram", api_key="...")
rag.ingest_audio("meeting.mp3", raw_bytes, transcriber=config)
```

Honest limitation: transcription quality is only as good as the underlying provider. Whisper (the default) is a strong general-purpose baseline, but has no built-in denoising - quiet or noisy audio genuinely degrades accuracy - and no domain-vocabulary biasing by default, so brand names and jargon commonly get mangled unless you pass a prompt hint. Accuracy also varies meaningfully by language. Use provider="deepgram" or pass a prompt hint if these matter for your use case.

Both providers use hosted APIs - no local model weights, no torch/CUDA dependency, consistent with keeping the base install light (the same reasoning behind reranking's optional [rerank] extra). Local/offline Whisper is not currently supported.

Verified live: a real Deepgram API call against synthesized speech correctly transcribed the audio and produced an accurate, grounded answer referencing what was actually said. Whisper's API shape was verified via a mocked call (no OpenAI key was available in this session), confirming the correct request structure without a live network round-trip.

## Video ingestion

ingest_video(filename, raw_bytes, transcriber=None) extracts the audio track from a video file (via ffmpeg) and transcribes it - the same transcriber= options and honest limitations as ingest_audio() apply, since this is audio ingestion plus an extraction step, not separate video-specific logic. Requires the ffmpeg binary installed on the system (not pip-installable - e.g. apt install ffmpeg on Debian/Ubuntu).

```python
rag.ingest_video("webinar.mp4", raw_bytes)
```

If the video already has a matching subtitle file (.vtt/.srt), ingesting that directly via ingest() is cheaper and more accurate than re-transcribing the audio - see Supported file formats.

Verification note: both the ffmpeg audio-extraction step and the transcription step are now fully verified live. ffprobe independently confirmed a real 3-second test video is extracted to a valid, playable audio stream of the correct duration. Separately, a real Deepgram API call against synthesized speech (via espeak) correctly transcribed the audio and produced an accurate, grounded answer referencing what was actually said - closing the gap noted in Audio ingestion, where live-provider testing was initially unavailable.

## Performance

Database connections are pooled internally (min 1, max 10 by default) rather than opened fresh on every call. Previously every ingest, ask, and memory operation opened a brand-new Postgres connection and closed it afterward - real, avoidable latency, especially under concurrent load (e.g. a web server handling multiple requests at once). This is automatic and requires no configuration.

Query embeddings are also cached in memory (LRU, 1000 entries by default) - repeated identical questions skip a redundant embedding call. This caches embeddings only, never full answers, since with conversation memory the same question can legitimately produce different answers depending on session history. Check cache effectiveness with rag.cache_stats(), or disable with cache_enabled=False.

## How it fits together
             +------------------+
             |   Your text or   |
             |  .txt/.pdf/.docx |
             +--------+---------+
                      |
             +--------v---------+
             |  rag.ingest(...)  |   chunk -> embed -> store
             +--------+---------+
                      |
             +--------v---------+
             |  PostgreSQL +     |
             |  pgvector         |
             +--------+---------+
                      |
             +--------v---------+
             |   rag.ask(...)    |   hybrid retrieve (dense + sparse, RRF)
             +--------+---------+          |
                      |                     v
             +--------v---------+   +---------------+
             |   Generation      |-->| Fallback chain |
             |  (temp/prompt/    |   | (if primary    |
             |   max_tokens)     |   |  fails)        |
             +--------+---------+   +---------------+
                      |
             +--------v---------+
             |  Conversation     |   optional: session_id ->
             |  memory (Postgres)|   prior turns injected as context
             +-------------------+

## Supported LLM providers

Gemini, Anthropic, and any OpenAI-compatible endpoint: OpenAI, Groq,
Mistral, Together, OpenRouter, Ollama, DeepSeek, xAI, Cohere,
Perplexity, or a custom endpoint (`provider="custom"` + `base_url=...`).
Install extras as needed: `pip install ragleap-rag[anthropic]`,
`[openai]`, or `[all]`.

## More examples

See [`examples/`](https://github.com/antonyrag/ragleap-core/tree/main/packages/ragleap-rag/examples)
in the source repo:
- `01_basic_ingest_and_ask.py` — the loop above, runnable as-is
- `02_streaming.py` — streaming responses
- `03_fallback_and_hybrid_search.py` — provider fallback + hybrid toggle
- `04_flask_web_api.py` — drop-in web API (works identically in FastAPI)

## Why this exists

Most RAG libraries give you a toolkit and leave production concerns
(retrieval quality, provider reliability, cost visibility) as an
exercise for you. `ragleap-rag` treats hybrid search, fallback, and
real token usage reporting as defaults, not add-ons — because a RAG
engine that silently fails on a rate limit, or that you can't verify
the actual cost of, isn't production-ready no matter how good its
retrieval is.

`ragleap-rag` is the foundation layer of
[ragleap-core](https://github.com/antonyrag/ragleap-core), a larger
open-source, self-hosted AI platform (channels, knowledge graph,
language detection, business integrations). Companion packages
(`ragleap-graph`, `ragleap-integrations`) are in progress.

## Status

Young, actively developed. Verified end-to-end: built, published to
PyPI, and independently confirmed working via `pip`, `uv`, and Google
Colab, in a genuinely separate environment from the development machine.

## License

MIT
