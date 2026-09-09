# ragleap-vectorstores

Pluggable vector backends beyond [ragleap-rag](https://pypi.org/project/ragleap-rag/)'s
built-in 6 (PgVector, FAISS, Pinecone, Weaviate, Qdrant, Milvus).

This package is under active development - more backends will be added
over time. See the
[roadmap](https://github.com/antonyrag/ragleap-core/wiki/Roadmap) for status.

## Available backends

| Backend | Extra | Notes |
|---|---|---|
| Chroma | `chroma` | Embedded/local via chromadb's PersistentClient - no server required. No native sparse/keyword search (`supports_sparse()` is `False`); hybrid search falls back to dense-only. |
| LanceDB | `lancedb` | Embedded/local via a directory path - no server required. Real upsert semantics via `merge_insert()`. No native sparse/keyword search enabled yet (`supports_sparse()` is `False`); hybrid search falls back to dense-only. |
| Redis | `redis` | Requires a real running server - Redis Stack, or plain Redis with the RediSearch module loaded (no embedded/local mode). `init_schema()` checks for the module and raises a clear error if it's missing. Metadata filtering only supports `document_id` (RediSearch requires predeclared schema fields). No native sparse/keyword search enabled yet (`supports_sparse()` is `False`); hybrid search falls back to dense-only. |
| Upstash Vector | `upstash` | Managed serverless REST API - no embedded/local mode at all, and the index (fixed dimension, dense-vs-hybrid type) must already exist, created via the Upstash console; `init_schema()` verifies compatibility via `info()` rather than creating anything. Metadata filtering supports arbitrary multi-key filters natively (real SQL-like `filter=` string over a genuine JSON dict) - more flexible than Redis here. No native sparse/keyword search enabled yet (`supports_sparse()` is `False`); hybrid search falls back to dense-only. |

## Design

Every backend here implements ragleap-rag's `VectorBackend` interface, so it
can be passed directly to `RagLeap(vector_backend=...)`. Each backend's real
client SDK is an optional extra - installing `ragleap-vectorstores` alone
pulls in no heavy dependencies beyond `ragleap-rag` itself.

## Install

```bash
pip install ragleap-vectorstores[chroma]
# or, with uv
uv add ragleap-vectorstores[chroma]

pip install ragleap-vectorstores[lancedb]
# or, with uv
uv add ragleap-vectorstores[lancedb]
```

## Usage

```python
from ragleap_vectorstores import ChromaBackend

backend = ChromaBackend(persist_directory="./chroma_data")
```

```python
from ragleap_vectorstores import LanceDBBackend

backend = LanceDBBackend(uri="./lancedb_data")
```

```python
from ragleap_vectorstores import RedisBackend

# Requires a real Redis Stack instance (or plain Redis + the RediSearch
# module) - plain Redis alone has no vector search.
backend = RedisBackend(redis_url="redis://localhost:6379/0")
```

```python
from ragleap_vectorstores import UpstashBackend

# Requires a real Upstash Vector index, created via the Upstash console
# (console.upstash.com) as a pure DENSE index - no embedded/local mode.
backend = UpstashBackend(url="https://...upstash.io", token="...")
```
