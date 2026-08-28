# ragleap-vectorstores

Pluggable vector backends beyond [ragleap-rag](https://pypi.org/project/ragleap-rag/)'s
built-in 6 (PgVector, FAISS, Pinecone, Weaviate, Qdrant, Milvus).

**Status: scaffold only - no backends implemented yet.** This package is
under active development. See the
[roadmap](https://github.com/antonyrag/ragleap-core/wiki/Roadmap) for status.

## Design

Every backend here implements ragleap-rag's `VectorBackend` interface, so it
can be passed directly to `RagLeap(vector_backend=...)`. Each backend's real
client SDK is an optional extra - installing `ragleap-vectorstores` alone
pulls in no heavy dependencies beyond `ragleap-rag` itself.

## Install

```bash
pip install ragleap-vectorstores[<backend>]
```

(No backends published yet.)
