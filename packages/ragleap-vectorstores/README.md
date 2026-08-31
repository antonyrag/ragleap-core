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

## Design

Every backend here implements ragleap-rag's `VectorBackend` interface, so it
can be passed directly to `RagLeap(vector_backend=...)`. Each backend's real
client SDK is an optional extra - installing `ragleap-vectorstores` alone
pulls in no heavy dependencies beyond `ragleap-rag` itself.

## Install

```bash
pip install ragleap-vectorstores[chroma]
# or
pip install ragleap-vectorstores[lancedb]
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
