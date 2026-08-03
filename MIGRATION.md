# Migrating to ragleap-rag

This guide shows real, runnable code comparisons for moving a basic RAG
setup from **LangChain** or **LlamaIndex** to `ragleap-rag`. Every
`ragleap-rag` snippet below matches the actual installed API (verified via
`inspect.signature()` against v0.11.1 — see the project's `CHANGELOG.md`).

> **A note on accuracy:** LangChain's and LlamaIndex's APIs change fairly
> often between versions. The snippets below reflect patterns that have
> been broadly stable, but if something doesn't run against your installed
> version, that's a sign the framework moved on, not that `ragleap-rag`'s
> side is wrong. Please verify against your own installed versions before
> relying on this for a real migration — we'd rather you catch a mismatch
> than trust an unverified comparison.

---

## 1. Basic ingest + query

### LangChain (before)

```python
from langchain_community.vectorstores import PGVector
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain.chains import RetrievalQA
from langchain.text_splitter import RecursiveCharacterTextSplitter

embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash")

splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
docs = splitter.create_documents([raw_text])

vectorstore = PGVector.from_documents(
    documents=docs,
    embedding=embeddings,
    connection_string="postgresql://user:pass@localhost:5432/mydb",
)

qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    retriever=vectorstore.as_retriever(search_kwargs={"k": 5}),
)

answer = qa_chain.invoke({"query": "What is the budget?"})
```

**What you had to manage yourself:** text splitting, embedding client setup,
vectorstore connection wiring, retriever configuration, and chain assembly —
four separate concepts before you can ask a single question.

### LlamaIndex (before)

```python
from llama_index.core import VectorStoreIndex, Document, StorageContext
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.embeddings.gemini import GeminiEmbedding
from llama_index.llms.gemini import Gemini
from llama_index.core import Settings

Settings.embed_model = GeminiEmbedding(model_name="models/gemini-embedding-001")
Settings.llm = Gemini(model="models/gemini-3.6-flash")

vector_store = PGVectorStore.from_params(
    database="mydb", host="localhost", password="pass",
    user="user", table_name="my_vectors", embed_dim=3072,
)
storage_context = StorageContext.from_defaults(vector_store=vector_store)

index = VectorStoreIndex.from_documents(
    [Document(text=raw_text)], storage_context=storage_context,
)

query_engine = index.as_query_engine(similarity_top_k=5)
response = query_engine.query("What is the budget?")
```

### ragleap-rag (after)

```python
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

rag = RagLeap(
    database_url="postgresql://user:pass@localhost:5432/mydb",
    primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="..."),
    embedder=EmbeddingConfig(
        provider="gemini", model="models/gemini-embedding-001",
        dimensions=3072, api_key="...",
    ),
)
rag.init_schema()
rag.ingest_text(filename="doc.txt", text=raw_text)

result = rag.ask("What is the budget?")
print(result["answer"])
```

No manual text splitting (chunking is handled internally), no separate
vectorstore/embedding-client wiring, no retriever object, no chain
assembly. `database_url` is the only connection string you manage —
pgvector setup happens via `init_schema()`.

---

## 2. Provider fallback (if one API is down or rate-limited)

### LangChain (before)

LangChain has no first-class automatic fallback between providers for a
single `.invoke()` call — this typically requires hand-rolled retry logic:

```python
def ask_with_fallback(query):
    try:
        return primary_chain.invoke({"query": query})
    except Exception:
        return fallback_chain.invoke({"query": query})
```

You're responsible for defining, testing, and maintaining this yourself,
including tracking which provider actually answered.

### ragleap-rag (after)

```python
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

rag = RagLeap(
    database_url="postgresql://user:pass@localhost:5432/mydb",
    primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="..."),
    fallbacks=[
        ProviderConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="..."),
        ProviderConfig(provider="openai", model="gpt-4o-mini", api_key="..."),
    ],
    embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001",
                              dimensions=3072, api_key="..."),
)
rag.init_schema()

result = rag.ask("What is the budget?")
print(result["provider_used"])   # tells you which one actually answered
print(result["model_used"])
```

Fallback chaining, plus knowing which provider actually served the
request, is built in — not something you write and maintain yourself.

---

## 3. Cost tracking

### LangChain (before)

LangChain's built-in callback handlers report token counts for some
providers, but computing real dollar cost, enforcing a monthly budget, or
auto-downgrading to a cheaper model when a budget is hit all require
custom code you write and maintain.

### ragleap-rag (after)

```python
rag = RagLeap(
    database_url="postgresql://user:pass@localhost:5432/mydb",
    primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="..."),
    embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001",
                              dimensions=3072, api_key="..."),
    budget_usd_per_month=50.0,
    budget_fallback=ProviderConfig(provider="ollama", model="llama3.2", base_url="http://localhost:11434/v1"),
)
rag.init_schema()

result = rag.ask("What is the budget?")
print(result["cost"])
# {'cost_usd': 0.0023, 'cumulative_cost_usd': 4.51, 'pricing_available': True}
```

Once `cumulative_cost_usd` crosses `budget_usd_per_month`, requests
automatically route to `budget_fallback` instead of failing or silently
overspending.

---

## 4. Swapping vector backends

### LangChain / LlamaIndex (before)

Both frameworks support multiple vector stores, but switching requires
changing the import, the constructor call, and often the connection
parameters — different backends have meaningfully different APIs.

### ragleap-rag (after)

```python
from ragleap.vectorstores import FAISSBackend, PgVectorBackend

# pgvector (default if vector_backend is omitted)
rag = RagLeap(database_url="...", vector_backend=PgVectorBackend("postgresql://..."),
              primary=..., embedder=...)

# swap to FAISS — everything else about calling rag.ingest_text() / rag.ask() is unchanged
rag = RagLeap(database_url="...", vector_backend=FAISSBackend(persist_directory="/data/faiss"),
              primary=..., embedder=...)
```

`database_url` is still required even with FAISS, since conversation
history is always stored in Postgres regardless of which vector backend
you choose — everything else about your ingest/query code stays identical
across backends.

---

## 5. What you gain, what you give up

| | LangChain / LlamaIndex | ragleap-rag |
|---|---|---|
| Integration breadth | 600+ integrations (LangChain) | 8 embedding providers, 6 vector backends, any OpenAI-compatible endpoint via `provider="custom"` |
| Agent/orchestration features | Yes (LangGraph, LlamaIndex agents) | No — out of scope by design, see `ROADMAP.md` |
| Automatic provider fallback | Hand-rolled | Built in |
| Cost tracking + budget-based auto-downgrade | Hand-rolled | Built in |
| Setup complexity for basic RAG | Multiple objects (splitter, embeddings, vectorstore, chain/query-engine) | One `RagLeap(...)` object |
| Community size / maturity | Much larger, longer track record | Newer, smaller — evaluate accordingly |

`ragleap-rag` is intentionally a focused RAG library, not a general
orchestration framework — see `ROADMAP.md`'s "Considered and Rejected"
section for why we've kept it that way rather than expanding scope to
match LangChain/LlamaIndex feature-for-feature.

---

## Getting help with your specific migration

If your setup uses a LangChain/LlamaIndex feature not shown here (custom
retrievers, reranking, memory/session handling, structured output), open
an issue on `antonyrag/ragleap-core` describing your current setup — real
migration examples are more useful than we can anticipate in advance, and
we'd rather add a verified example than guess at one.
