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
    embedder_api_key="...",
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
             +-------------------+   +---------------+

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
