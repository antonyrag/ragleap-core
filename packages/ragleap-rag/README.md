# ragleap-rag

**A fast, honest, self-hosted RAG engine.** Hybrid dense+sparse retrieval,
real streaming, automatic provider fallback, and actual token usage
numbers — not estimates. Bring your own API keys; nothing is routed
through us.

```bash
pip install ragleap-rag
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
    embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", dimensions=3072, api_key="your-gemini-key"),
    primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="your-gemini-key"),
)
rag.init_schema()  # one-time, idempotent — safe to call every run

rag.ingest_text("handbook.txt", "Employees get unlimited PTO and a $500/year learning budget.")

answer = rag.ask("How much PTO do employees get?")
print(answer["answer"])
```
Employees get unlimited PTO. (Source 1)

That's the whole loop: ingest text (or a `.txt`/`.pdf`/`.docx` file via
`rag.ingest(filename, raw_bytes)`), then ask questions grounded in it.

## Vector backends

By default, `RagLeap` stores vectors in Postgres/pgvector - the `database_url` you already pass in. Conversation memory always uses this same Postgres connection regardless of which vector backend you choose, since memory (session history) is a separate concern from vector storage.

You can swap the vector backend via `vector_backend=`:

```python
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap.vectorstores import FAISSBackend

rag = RagLeap(
    database_url="postgresql://user:pass@localhost/mydb",  # still required, for conversation memory
    vector_backend=FAISSBackend(persist_directory="./my_faiss_data"),  # vectors go here instead
    embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", dimensions=3072, api_key="..."),
    primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="..."),
)
rag.init_schema()
```

Currently available:

| Backend | Extra | Sparse/hybrid search | Notes |
|---|---|---|---|
| `PgVectorBackend` (default) | none needed | Yes - real Postgres full-text search | Battle-tested, the original implementation |
| `FAISSBackend` | `pip install ragleap-rag[faiss]` | No - `ask(hybrid=True)` gracefully degrades to dense-only | Local, in-process, no API key. Pass `persist_directory=` for data that survives restarts - without it, everything is in-memory and lost on process exit. Metadata filtering is a post-filter (over-fetch then filter), not an indexed query - fine for small-to-medium datasets, less efficient than pgvector's JSONB GIN index at large scale. |
| `PineconeBackend` | `pip install ragleap-rag[pinecone]` | No - `ask(hybrid=True)` gracefully degrades to dense-only | Managed, serverless. **Not live-verified** - no Pinecone account was available during development; code-complete against the real installed SDK's actual source (not just docs), but treat as best-effort until confirmed live. `persist_directory=` is **required** (not optional like FAISS) - Pinecone vectors persist remotely regardless of local state, so a SQLite sidecar for chunk text is mandatory to avoid orphaned vectors after a restart. `metadata_filter` uses Pinecone's real native filtering, not a post-filter. |
| `WeaviateBackend` | `pip install ragleap-rag[weaviate]` | No (Weaviate natively supports BM25/hybrid search, but that's not wired in yet - a real future enhancement) | Managed cloud or self-hosted. **Not live-verified** - same caveat as Pinecone. `persist_directory=` required, same reasoning. Vectors are "self-provided" (bring-your-own-embeddings) - Weaviate's built-in vectorizer integrations aren't used. |
| `QdrantBackend` | `pip install ragleap-rag[qdrant]` | No (Qdrant natively supports sparse vectors/hybrid search, not wired in yet) | Managed cloud or self-hosted. **Not live-verified** - same caveat. `persist_directory=` required, same reasoning. |
| `MilvusBackend` | `pip install ragleap-rag[milvus]` | No (Milvus natively supports sparse/BM25/hybrid search, not wired in yet) | Managed (Zilliz Cloud) or self-hosted. **Not live-verified** - same caveat. `persist_directory=` required, same reasoning. Unlike the other three, Milvus accepts arbitrary string primary keys directly - no UUID workaround needed. |

```python
from ragleap.vectorstores import PineconeBackend  # or WeaviateBackend, QdrantBackend, MilvusBackend

rag = RagLeap(
    database_url="postgresql://user:pass@localhost/mydb",
    vector_backend=PineconeBackend(persist_directory="./pinecone_meta", api_key="...", index_name="my-index"),
    embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", dimensions=3072, api_key="..."),
    primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="..."),
)
```

**Live-verification status for Pinecone/Weaviate/Qdrant/Milvus**: none of the four have been tested against a real account - no accounts were available during development. Each was still built with real rigor: every SDK method signature, class field, and return type used was introspected directly against the actual installed client package's source code (not assumed from documentation or memory), which caught a real bug pre-ship for `PineconeBackend` (dict-style access that would have failed at runtime against the SDK's actual `msgspec.Struct`-based response objects). Treat all four as best-effort until confirmed live by someone with a real account - the same honest standard already applied to `mistral`/`together`/`cohere`/`voyage` in the embedding module.

Building your own backend is straightforward: implement the `ragleap.vectorstores.VectorBackend` abstract interface (`init_schema`, `insert_document`, `insert_chunk`, `search_dense`, `list_documents`, `delete_document`, `get_document_filename`, and optionally `search_sparse`/`search_hybrid`/`supports_sparse` if your backend can do keyword search).

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
    embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", dimensions=3072, api_key="..."),
    primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="..."),
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

`ask_stream()` supports `rerank=` and `metadata_filter=`, the same as
`ask()` - these were missing from the streaming variant until 0.5.7,
a genuine API inconsistency now fixed.

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

The reranker runs on ONNX Runtime (CPU only) rather than torch/sentence-transformers - a quantized cross-encoder model (~23MB) downloads once on the first rerank=True call and is cached locally by huggingface_hub, not at RagLeap construction time. This avoids the 2GB+ torch+CUDA install that sentence-transformers pulled in even for CPU-only use in versions before 0.5.8.

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

## Query rewriting

Pass `query_rewrite=` to `ask()` to transform the query before it's embedded/searched - can improve retrieval quality, at the cost of one extra LLM call (or more, for `multi_query`). Grounded in established RAG research: HyDE (Gao et al. 2022), RAG-Fusion/multi-query (Rackauckas 2023).

```python
# Resolves follow-up questions using conversation history - needs session_id
rag.ask("What about pricing?", session_id="s1", query_rewrite="contextual")

# Generates a hypothetical answer and embeds that instead of the raw query
rag.ask("What is RagLeap's pricing?", query_rewrite="hyde")

# Generates alternative phrasings, retrieves for each, merges via Reciprocal Rank Fusion
result = rag.ask("What is RagLeap's pricing?", query_rewrite="multi_query", multi_query_n=3)
print(result["query_rewrite"])  # {"strategy": "multi_query", "query_variants": [...]}
```

Three strategies, each suited to a different problem:

- **`"contextual"`** - rewrites a follow-up question ("what about its pricing?") into a standalone question using `session_id` conversation history. No-ops (uses the original query) if there's no history yet. One extra LLM call, no extra retrieval calls.
- **`"hyde"`** - generates a hypothetical answer passage and embeds *that* instead of the raw query. Often a better semantic match than embedding a short question, since the hypothetical is closer in length/style to your actual corpus documents. One extra LLM call, no extra retrieval calls.
- **`"multi_query"`** - generates `multi_query_n` alternative phrasings (default 3), retrieves separately for each, merges via Reciprocal Rank Fusion. Can improve recall by covering more of the query's "intent space" - but honestly, generated variants can be "nearly identical and lacking in diversity" (a documented limitation in the broader RAG-Fusion literature, not unique to this implementation), and it costs `multi_query_n` retrieval calls instead of one. If you want the cheap, fast option, use `"contextual"` or `"hyde"` instead.

**The final answer generation always uses your original query, never the rewritten form** - rewriting only affects what gets retrieved, not what the model is asked to answer. Every strategy fails open: if the extra LLM call itself fails for any reason, retrieval proceeds with the original, unmodified query - a broken rewrite step can never break retrieval entirely.

The result gains a `query_rewrite` field with the strategy used and what was actually retrieved-with (`rewritten_query`, `hyde_document`, or `query_variants`) whenever a strategy is set; it's absent entirely when `query_rewrite=` isn't passed, for backward compatibility. The extra LLM call's real token cost is recorded into the existing cost-tracking infrastructure (see Cost tracking), contributing to `cumulative_cost_usd`.

Not currently supported on `ask_stream()`.

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

## Guardrails

Beyond the built-in sanitization above, `input_guardrails=`/`output_guardrails=` let you plug in your own validation callbacks - a PII filter, a profanity check, a brand-voice check, whatever your use case needs. Each guardrail is a function `(text: str) -> str` that returns the (possibly modified) text, or raises `GuardrailViolation` to reject it outright.

```python
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap.guardrails import GuardrailViolation

def reject_pii(text: str) -> str:
    if "ssn:" in text.lower():
        raise GuardrailViolation("Document appears to contain an SSN")
    return text

def enforce_brand_voice(text: str) -> str:
    return text.replace("gonna", "going to")

rag = RagLeap(
    database_url="...",
    embedder=EmbeddingConfig(...),
    primary=ProviderConfig(...),
    input_guardrails=[reject_pii],       # runs during ingest_text(), after sanitization
    output_guardrails=[enforce_brand_voice],  # runs on ask()/ask_stream()'s answer
)
```

On `ask()`, a raised `GuardrailViolation` replaces the answer with a refusal message and sets `answer["guardrail_blocked"] = True` (the key is only present when guardrails are configured). On `ingest_text()`, a violation aborts ingestion entirely - nothing is stored.

Honest limitation for `ask_stream()`: output guardrails can only run *after* the full answer is assembled, but by then individual tokens have already been yielded to the caller - streaming can't retroactively un-send content. A violation during streaming is logged as a warning, not enforced. If blocking bad output before the user sees any of it matters for your use case, use `ask()` instead of `ask_stream()`.

## Evaluation

`rag.evaluate(test_cases)` runs a labeled test set through `ask()` and reports deterministic quality signals - it is **not** an LLM-as-judge framework (no faithfulness/relevancy scoring like Ragas). It measures three things that don't require an LLM call themselves:

- **Retrieval hit rate** - did the expected document actually show up in `sources`?
- **Keyword coverage** - what fraction of expected keywords appear in the generated answer?
- **Citation groundedness** - of the keywords found in the answer, how many also appear in the chunks the answer actually cited? A low score here is a real (if heuristic) hallucination signal.

```python
result = rag.evaluate([
    {"query": "What's the refund policy?", "expected_document": "policy.pdf", "expected_keywords": ["30 days", "receipt"]},
    {"query": "How do I reset my password?", "expected_document": "faq.pdf", "expected_keywords": ["settings", "email link"]},
])

print(result["retrieval_hit_rate"])       # 1.0
print(result["keyword_coverage_rate"])    # 0.75
print(result["groundedness_rate"])        # 0.9
print(result["results"][0])               # per-case detail: query, answer, sources, hits
```

Any extra keyword arguments (`top_k=`, `rerank=`, `hybrid=`, `metadata_filter=`, etc.) are passed through to every `ask()` call the evaluation makes. This is a fast, free, repeatable sanity check for catching regressions in your own retrieval/generation setup - not a substitute for human review, and not a claim of measuring "truthfulness." A full LLM-as-judge evaluation framework is planned as a separate, dedicated tool (see the project roadmap).

## Observability hooks

`on_ingest=`/`on_query=`/`on_answer=` are lightweight, fire-and-forget event emission points - not a dashboard or storage layer, just an instrumentation seam for logging, metrics, tracing, or a future observability tool to plug into. Each is a list of callables `(event: dict) -> None`.

```python
import logging
logger = logging.getLogger("ragleap.events")

rag = RagLeap(
    database_url="...",
    embedder=EmbeddingConfig(...),
    primary=ProviderConfig(...),
    on_ingest=[lambda e: logger.info(f"Ingested {e['filename']}: {e['chunks_stored']} chunks")],
    on_query=[lambda e: logger.info(f"Query: {e['query']!r} (hybrid={e['hybrid']}, streaming={e['streaming']})")],
    on_answer=[lambda e: logger.info(f"Answered via {e.get('provider_used')}, usage={e.get('usage')}")],
)
```

A hook that raises an exception is caught, logged as a warning, and swallowed - it never breaks the actual ingest/ask call. This is fire-and-forget, not a delivery guarantee: if a hook is slow or fails, that's on the hook, not on your RAG pipeline.

`on_answer` fires on both `ask()` (with `provider_used`, `usage`, `chunks_sent`, `guardrail_blocked`) and `ask_stream()` (with `answer_length`, since usage isn't available for streaming - see the Streaming section). Every event includes `streaming: bool` so one handler can distinguish the two if needed.

## Cost tracking

Every `ask()` call returns a `cost` field computed from the real, provider-reported token usage - `{"cost_usd": float | None, "cumulative_cost_usd": float, "pricing_available": bool}`. `cost_usd` is `None` whenever the provider/model isn't in the pricing table, never a guessed number.

```python
rag = RagLeap(
    database_url="...",
    embedder=EmbeddingConfig(...),
    primary=ProviderConfig(provider="anthropic", model="claude-sonnet-5", ...),
    pricing_table={"anthropic": {"claude-sonnet-5": {"input": 2.00, "output": 10.00}}},  # optional, merges with/overrides the seed table
    budget_usd_per_month=50.0,
    budget_fallback=ProviderConfig(provider="ollama", model="llama3"),  # used once budget is crossed
)

result = rag.ask("A question")
print(result["cost"])  # {"cost_usd": 0.000053, "cumulative_cost_usd": 0.000053, "pricing_available": True}
```

The built-in seed pricing table covers Gemini, Anthropic, and OpenAI only, verified against provider pricing pages on 2026-07-28. **LLM pricing changes fast** - three major providers each shipped new pricing tiers within the same week this table was built. Pass `pricing_table=` to override or extend it; your entries always win over the seed table. This is the expected, normal way to keep costs accurate, not an edge case.

`budget_usd_per_month` + `budget_fallback` implement budget-triggered fallback: once cumulative spend crosses the budget, subsequent `ask()` calls use `budget_fallback` instead of the configured primary/fallback chain for that call only - the shared `RagLeap` instance's own primary/fallbacks are never mutated, so concurrent `ask()` calls from other requests aren't affected by one request's fallback decision. If `budget_usd_per_month` is set with no `budget_fallback`, spend is tracked but nothing ever switches providers.

Honest limitations: `ask_stream()` never reports a `cost_usd` (streaming has no token usage data available - see the Streaming section), though `override_provider` still applies for budget-triggered fallback if you've configured one. The cumulative spend counter is a simple in-process running total, not a thread-safe, precise, multi-worker ledger - fine for a single process tracking its own approximate spend, not for aggregating exact costs across many concurrent workers (use the `on_answer` observability hook to aggregate `cost_usd` externally for that instead).

## Structured output

Pass `response_format=` (a JSON schema dict) to `ask()` to get validated structured data alongside the usual prose answer. Install the `[structured]` extra (`pip install ragleap-rag[structured]`) for real schema validation via `jsonschema` - without it, only a basic top-level type check runs, and the result honestly says so.

```python
schema = {
    "type": "object",
    "properties": {
        "city": {"type": "string"},
        "country": {"type": "string"},
        "population_millions": {"type": "number"},
    },
    "required": ["city", "country", "population_millions"],
}

result = rag.ask("What city is this, what country, and its population?", response_format=schema)
print(result["structured"])                  # {"city": "Chennai", "country": "India", "population_millions": 11}
print(result["structured_valid"])             # True
print(result["structured_enforcement"])       # "native" or "json_object_fallback"
print(result["structured_validation_method"]) # "jsonschema" or "basic_type_check_only"
print(result["answer"])                        # still the JSON as a string, for backward compatibility
```

**Per-provider enforcement, live-verified this release with a real Gemini call** (not mocked): Gemini uses native `response_schema` constrained decoding. Anthropic has no OpenAI-style `response_format` - the documented mechanism is forcing a single tool call whose `input_schema` is the desired shape, then reading the tool's parsed input directly. Both report `structured_enforcement: "native"`. OpenAI-compatible providers (OpenAI, Mistral, Together, Ollama) try strict `json_schema` mode first; not every one of them supports it, so on failure this honestly falls back to unconstrained `json_object` mode and reports `structured_enforcement: "json_object_fallback"` rather than pretending the guarantee is the same.

`structured_valid` reflects real validation against your schema (`required` fields, types, etc.) when `jsonschema` is installed - `structured_enforcement: "native"` means the provider *tried* to follow the schema, not that the result is guaranteed valid; always check `structured_valid` before trusting the shape. Without the `[structured]` extra, `structured_validation_method` will be `"basic_type_check_only"` - it confirms the top-level type (object/array/etc.) but can't catch a missing `required` field or a wrong nested type.

Not currently supported on `ask_stream()` - structured output needs the complete response before it's valid JSON, so streaming it defeats the purpose. This is a real gap, not an oversight; token-level streaming of partial JSON is a distinct feature that may come later.

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

Not limited to Whisper and Deepgram - provider="custom" accepts any transcription function you supply, so you can use AssemblyAI, Speechmatics, Azure Speech, AWS Transcribe, or anything else without waiting on ragleap-rag to add native support.

```python
def my_transcriber(filename: str, audio_bytes: bytes) -> str:
    # call whatever provider/SDK you prefer
    return transcript_text

config = TranscriptionConfig(provider="custom", transcribe_fn=my_transcriber)
rag.ingest_audio("call.mp3", raw_bytes, transcriber=config)
```

Verified live: a real Deepgram API call against synthesized speech correctly transcribed the audio and produced an accurate, grounded answer referencing what was actually said. Whisper's API shape was verified via a mocked call (no OpenAI key was available in this session), confirming the correct request structure without a live network round-trip.

## Video ingestion

ingest_video(filename, raw_bytes, transcriber=None) extracts the audio track from a video file (via ffmpeg) and transcribes it - the same transcriber= options and honest limitations as ingest_audio() apply, since this is audio ingestion plus an extraction step, not separate video-specific logic. Requires the ffmpeg binary installed on the system (not pip-installable - e.g. apt install ffmpeg on Debian/Ubuntu).

```python
rag.ingest_video("webinar.mp4", raw_bytes)
```

If the video already has a matching subtitle file (.vtt/.srt), ingesting that directly via ingest() is cheaper and more accurate than re-transcribing the audio - see Supported file formats.

Verification note: both the ffmpeg audio-extraction step and the transcription step are now fully verified live. ffprobe independently confirmed a real 3-second test video is extracted to a valid, playable audio stream of the correct duration. Separately, a real Deepgram API call against synthesized speech (via espeak) correctly transcribed the audio and produced an accurate, grounded answer referencing what was actually said - closing the gap noted in Audio ingestion, where live-provider testing was initially unavailable.

## Batch ingestion

`rag.ingest_batch(items)` ingests a list of mixed-type items concurrently, and returns a per-item result rather than raising on the first failure - one bad item never blocks or rolls back the others.

```python
results = await rag.ingest_batch([
    {"type": "file", "filename": "notes.txt", "raw_bytes": b"..."},
    {"type": "url", "url": "https://example.com/article"},
    {"type": "image", "filename": "scan.png", "raw_bytes": b"...", "mode": "ocr"},
    {"type": "audio", "filename": "call.mp3", "raw_bytes": b"..."},
])

for r in results:
    if r["success"]:
        print(r["result"])
    else:
        print("failed:", r["error"])
```

Each item dict needs a `"type"` key (`"file"`, `"url"`, `"image"`, `"audio"`, or `"video"`) plus whatever kwargs that type's `ingest_*` method normally needs. Verification note: tested with a real 4-item mixed batch (a .txt file, a live URL fetch, a deliberately corrupt fake PDF, and a .json file) - 3 of 4 succeeded exactly as expected, and the corrupt PDF failed cleanly with a clear logged error rather than crashing the batch or silently affecting the other results.

## Performance

Database connections are pooled internally (min 1, max 10 by default) rather than opened fresh on every call. Previously every ingest, ask, and memory operation opened a brand-new Postgres connection and closed it afterward - real, avoidable latency, especially under concurrent load (e.g. a web server handling multiple requests at once). This is automatic and requires no configuration.

Query embeddings are also cached in memory (LRU, 1000 entries by default) - repeated identical questions skip a redundant embedding call. This caches embeddings only, never full answers, since with conversation memory the same question can legitimately produce different answers depending on session history. Check cache effectiveness with rag.cache_stats(), or disable with cache_enabled=False.

For multi-process deployments (multiple Gunicorn or Celery workers), the in-memory cache doesn't help across processes - each worker has its own separate cache, so a hit in one worker is invisible to the others. Setting `cache_backend="redis"` (with the `[redis]` extra and a `redis_url`) shares the query embedding cache across all worker processes via Redis, with a configurable `cache_ttl_seconds` (default 86400 = 24h).

```python
rag = RagLeap(
    database_url="...",
    embedder=EmbeddingConfig(...),
    primary=ProviderConfig(...),
    cache_backend="redis",
    redis_url="redis://localhost:6379/0",
    cache_ttl_seconds=86400,
)
```

Verification note: proven with two separate `RagLeap` instances (simulating two separate worker processes) pointed at the same Redis - the first instance's cache miss and resulting embedding write was correctly picked up as a cache hit on the second, completely separate instance's first call, confirming the embedding is genuinely shared across process boundaries and not just cached within one Python object.

## Celery integration

Running ingestion or asking as background tasks (so a web request doesn't block on an LLM call) is a common pattern. The one thing that matters: **RagLeap's connection pool is per-instance and not fork-safe across processes.** Create one global `RagLeap` object before Celery's default "prefork" pool forks workers, and every worker inherits the same pool and file descriptors - this shows up later as hung queries or connection errors under concurrent load, not as an obvious startup crash.

The fix: each worker process builds its own `RagLeap` instance, once, after it forks - not at module import time.

```python
from celery import Celery
from celery.signals import worker_process_init
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

app = Celery("ragleap_tasks", broker="redis://localhost:6379/0", backend="redis://localhost:6379/0")

_rag_instance = None

def get_rag() -> RagLeap:
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = RagLeap(
            database_url="postgresql://...",
            embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", dimensions=3072, api_key="..."),
            primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="..."),
            # Same Redis server as the broker above is fine - a different
            # db index keeps the query cache and the task queue from colliding.
            cache_backend="redis",
            redis_url="redis://localhost:6379/1",
        )
        _rag_instance.init_schema()
    return _rag_instance

@worker_process_init.connect
def init_worker(**kwargs):
    get_rag()  # built right after fork, not before

@app.task(name="ragleap.ingest_text")
def ingest_text_task(filename: str, text: str, metadata: dict | None = None):
    result = get_rag().ingest_text(filename=filename, text=text, metadata=metadata)
    return {"document_id": result.document_id, "chunks_stored": result.chunks_stored}

@app.task(name="ragleap.ask")
def ask_task(query: str, session_id: str | None = None):
    answer = get_rag().ask(query, session_id=session_id)
    return {"answer": answer["answer"], "sources": answer["sources"]}
```

Architecture:

```
                    +-----------+
  Web request  ---> |   Redis   | ---> worker process 1 (own RagLeap + pool)
  (non-blocking)    |  broker   | ---> worker process 2 (own RagLeap + pool)
                    +-----------+                |
                                                  v
                                          +---------------+
                                          |   PostgreSQL   |
                                          |   + pgvector   |
                                          +---------------+
                                                  ^
                                                  |
                                   (optional) Redis query cache,
                                   shared across all worker processes
```

Each worker process talks to the same Postgres database and, optionally, shares the Redis query cache (a separate concern from the Celery broker/backend, even if it's the same Redis server). Run `celery -A your_module worker --loglevel=info` to start a worker, then call `.delay(...)` from your web app to enqueue tasks without blocking the request. This example omits `vector_backend=`, so it uses the default pgvector - swapping in FAISS, Pinecone, Weaviate, Qdrant, or Milvus works identically in this same Celery pattern, since only the RagLeap construction inside `get_rag()` changes.

See `examples/05_celery_background_tasks.py` for the full runnable version.

## How it fits together
             +------------------+
             | Text, 28 formats |
             |  URLs, images,   |
             |   audio, video   |
             +--------+---------+
                      |
             +--------v---------+
             |  rag.ingest(...)  |   chunk -> embed -> store
             +--------+---------+
                      |
             +--------v---------+
             |  Vector backend   |   pgvector (default), or FAISS/Pinecone/
             |  (pluggable)      |   Weaviate/Qdrant/Milvus via vector_backend=
             +--------+---------+
                      |
             +--------v---------+
             |   rag.ask(...)    |
             +--------+---------+
                      |
             +--------v---------+
             | query_rewrite=    |   optional: "contextual"/"hyde"/"multi_query"
             | (optional)        |   transforms the query before retrieval
             +--------+---------+
                      |
             +--------v---------+
             |  Hybrid retrieve  |   dense + sparse (RRF) - degrades to
             |                   |   dense-only if the backend can't do sparse
             +--------+---------+          |
                      |                     v
             +--------v---------+   +---------------+
             |   Generation      |-->| Fallback chain |
             |  (temp/prompt/    |   | (if primary    |
             |   response_format)|   |  fails)        |
             +--------+---------+   +---------------+
                      |
             +--------v---------+
             |  Cost tracking +  |   real token usage -> cost_usd; output
             |  guardrails       |   guardrails run on the answer
             +--------+---------+
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

**`model=` is always required** (constructor arg or the relevant env var, e.g. `GEMINI_CHAT_MODEL`/`ANTHROPIC_MODEL`) - `ragleap-rag` never hardcodes a default model for any provider. This was a deliberate v0.9.0 decision, not an oversight: a hardcoded Gemini default broke in production mid-project when Google deprecated it, and there's no model string (pinned or a provider's own "-latest" alias) that stays safe indefinitely - even Google's own `-latest` aliases have been deprecated before. Rather than trade one staleness risk for another, the library just always asks you to know and specify your model.

## Supported embedding providers

```python
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

rag = RagLeap(
    database_url="...",
    embedder=EmbeddingConfig(provider="ollama", model="nomic-embed-text", dimensions=768),  # local, no API key, no cost
    primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="..."),
)
```

Gemini, OpenAI, Mistral, Together, and Ollama (all OpenAI-compatible under the hood, no new dependency), plus Cohere and Voyage AI (own API shapes, via `requests`). Mistral/Together/Ollama reuse the `openai` package's client pointed at a different `base_url` — install the `[openai]` extra for any of them (`pip install ragleap-rag[openai]`), even if you don't have an OpenAI account or key; it's the underlying HTTP client library, not an OpenAI dependency in the account sense.

**`model=` and `dimensions=` are always required** for every embedding provider (constructor arg or env var, e.g. `GEMINI_EMBEDDING_MODEL`/`EMBEDDING_DIMENSIONS`) - same reasoning as generation providers above. `dimensions=` in particular can't be safely inferred without assuming a specific model, so it's mandatory everywhere now, not just for `together` (which set this precedent from the start).

**Live-verification status**, following this project's own standard of testing against real infrastructure before calling anything done: `gemini` and `openai` are long-verified. `ollama` was live-verified this release — fully local, no API key, tested end-to-end through real ingestion + real FAISS retrieval. `mistral`, `together`, `cohere`, and `voyage` are code-complete based on public API documentation but **not live-verified** against a real account - the same category of caveat as the `PineconeBackend` vector backend (see Vector backends above).

`provider="custom"` + `base_url=...` reaches any OpenAI-compatible embeddings endpoint not otherwise named above - a self-hosted server (vLLM, LM Studio, etc.), or a provider without dedicated code here yet. Several Chinese providers - Qwen/DashScope, Zhipu/GLM, Moonshot/Kimi - ship OpenAI-compatible modes and work via this path today. Mirrors `generation.py`'s existing `provider="custom"` support for chat models.

Honest limitation for `cohere`: its API distinguishes query vs. document embeddings via an `input_type` parameter for better retrieval quality, but `embed_text()`/`embed_batch()` don't currently know which context they're called in — Cohere calls always use `input_type="search_document"`, which isn't optimal for query embeddings specifically.

## More examples

See [`examples/`](https://github.com/antonyrag/ragleap-core/tree/main/packages/ragleap-rag/examples)
in the source repo:
- `01_basic_ingest_and_ask.py` — the loop above, runnable as-is
- `02_streaming.py` — streaming responses
- `03_fallback_and_hybrid_search.py` — provider fallback + hybrid toggle
- `04_flask_web_api.py` — drop-in web API (works identically in FastAPI)
- `05_celery_background_tasks.py` — background ingestion/asking via Celery + Redis

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
