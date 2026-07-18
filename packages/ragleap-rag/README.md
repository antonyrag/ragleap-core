# ragleap-rag

A fast, honest, self-hosted RAG engine. Hybrid dense+sparse retrieval,
streaming, provider fallback, and real token usage reporting — no
vendor lock-in, bring your own API keys.

```bash
pip install ragleap-rag[gemini]
```

```python
from ragleap import RagLeap, ProviderConfig

rag = RagLeap(
    database_url="postgresql://user:pass@localhost/mydb",
    embedder_api_key="your-gemini-key",
    primary=ProviderConfig(provider="gemini", api_key="your-gemini-key"),
)
rag.init_schema()  # one-time, idempotent

with open("document.pdf", "rb") as f:
    result = rag.ingest("document.pdf", f.read())
print(f"Ingested {result.chunks_stored} chunks")

answer = rag.ask("What does this document say?")
print(answer["answer"])
print("Sources:", answer["sources"])
print("Tokens used:", answer["usage"])
```

## Why ragleap-rag

- **Hybrid search by default** — combines pgvector dense similarity with
  Postgres full-text sparse search via Reciprocal Rank Fusion, catching
  both semantic matches and exact keyword/identifier matches.
- **Real provider fallback** — configure backup LLM providers; if your
  primary fails (rate limit, outage, bad key), it retries automatically.
- **Streaming** — real per-provider streaming for Gemini, Anthropic, and
  any OpenAI-compatible endpoint.
- **Real token usage** — every answer reports actual `prompt_tokens`,
  `completion_tokens`, `total_tokens` from the provider's own response,
  not an estimate.
- **Context budget trimming** — automatically drops lowest-ranked chunks
  to stay within a character budget, so you're not paying for more
  context than necessary.
- **BYOK, always** — no system-provided keys, ever. You own your data,
  your database, and your API costs.

## Requirements

A PostgreSQL database with the [pgvector](https://github.com/pgvector/pgvector)
extension available (`CREATE EXTENSION vector` — `rag.init_schema()` handles
the rest). Embeddings currently use Google Gemini (`gemini-embedding-001`);
generation supports Gemini, Anthropic, and any OpenAI-compatible provider
(OpenAI, Groq, Mistral, Together, OpenRouter, Ollama, DeepSeek, xAI, Cohere,
Perplexity, or a custom endpoint).

## Status

This is a young, actively-developed extraction from
[ragleap-core](https://github.com/antonyrag/ragleap-core), the open-source
self-hosted RAG platform. Full documentation, more embedding providers, and
companion packages (`ragleap-graph` for knowledge-graph-boosted retrieval,
`ragleap-integrations` for CRM/database connectors) are in progress.

## License

MIT
