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
