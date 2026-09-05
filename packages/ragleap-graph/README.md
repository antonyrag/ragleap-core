# ragleap-graph

Knowledge-graph-augmented retrieval for RAG systems — entity extraction, co-occurrence graphs, and graph-based document retrieval via Neo4j.

```bash
pip install ragleap-graph
```

## Quickstart

```python
from ragleap_graph import GraphConfig, GraphIndex

graph = GraphIndex(config=GraphConfig(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="...",
))

graph.upsert_document(
    document_id="doc-1",
    title="Q3 Report",
    chunks=[{"text": "Acme Corp reported strong Q3 revenue growth."}],
)

docs = graph.find_documents_by_entities(["Acme Corp"])
related = graph.search_related_entities(["Acme Corp"], max_depth=2)
```

<!-- AUTO-STATS:START -->
**Current: v0.6.5** · 87 tests (86 passed, 1 skipped)
<!-- AUTO-STATS:END -->

## Architecture

<img src="https://mermaid.ink/svg/Zmxvd2NoYXJ0IFRECiAgICBjbGFzc0RlZiB3cml0ZSBmaWxsOiMxZTNhNWYsc3Ryb2tlOiM0YTkwZDksY29sb3I6I2ZmZgogICAgY2xhc3NEZWYgcmVhZCBmaWxsOiMxYTRkM2Esc3Ryb2tlOiMyMmM1NWUsY29sb3I6I2ZmZgogICAgY2xhc3NEZWYgaHlicmlkIGZpbGw6IzNkMjY0NSxzdHJva2U6I2E4NTVmNyxjb2xvcjojZmZmCiAgICBjbGFzc0RlZiBzdG9yZSBmaWxsOiM0ZDMzMTksc3Ryb2tlOiNmNTllMGIsY29sb3I6I2ZmZgoKICAgIHN1YmdyYXBoIFdyaXRlWyJXcml0ZSBwYXRoIl0KICAgICAgICBEb2NbImdyYXBoLnVwc2VydF9kb2N1bWVudCguLi4pIl06Ojp3cml0ZSAtLT4gRXh0cmFjdFsiRW50aXR5L3JlbGF0aW9uIGV4dHJhY3Rpb248YnIvPnJlZ2V4IGRlZmF1bHQsIExMTSB2aWEgbWV0aG9kPSdsbG0nIl06Ojp3cml0ZQogICAgICAgIEV4dHJhY3QgLS0-IERlZHVwWyJFbnRpdHlEZWR1cGxpY2F0b3IgKG9wdGlvbmFsKTxici8-ZGVkdXBfZW5hYmxlZD1UcnVlIl06Ojp3cml0ZQogICAgZW5kCgogICAgRGVkdXAgLS0-IE5lbzRqWyJOZW80aiBncmFwaDxici8-RW50aXR5LCBEb2N1bWVudCw8YnIvPlBhaXJXZWlnaHQsIFJlbGF0aW9uV2VpZ2h0Il06OjpzdG9yZQogICAgTmVvNGogLS0-IEVkZ2VzWyJDT05UQUlOUywgQ09fT0NDVVJTX1dJVEgsPGJyLz5SRUxBVEVTX0FTIGVkZ2VzIl06OjpzdG9yZQoKICAgIHN1YmdyYXBoIFJlYWRbIlJlYWQgcGF0aCJdCiAgICAgICAgRmluZERvY3NbImZpbmRfZG9jdW1lbnRzX2J5X2VudGl0aWVzKCkiXTo6OnJlYWQKICAgICAgICBTZWFyY2hSZWxbInNlYXJjaF9yZWxhdGVkX2VudGl0aWVzKCkiXTo6OnJlYWQKICAgICAgICBGaW5kUmVsWyJmaW5kX3JlbGF0aW9ucygpIl06OjpyZWFkCiAgICAgICAgRmluZFR5cGVbImZpbmRfZW50aXRpZXNfYnlfdHlwZSgpIl06OjpyZWFkCiAgICAgICAgTGluZWFnZVsiZmluZF9saW5lYWdlKCk8YnIvPnBlci1kb2N1bWVudCBjb250cmlidXRpb24gbG9va3VwIl06OjpyZWFkCiAgICBlbmQKICAgIE5lbzRqIC0tPiBGaW5kRG9jcwogICAgTmVvNGogLS0-IFNlYXJjaFJlbAogICAgTmVvNGogLS0-IEZpbmRSZWwKICAgIE5lbzRqIC0tPiBGaW5kVHlwZQogICAgTmVvNGogLS0-IExpbmVhZ2UKCiAgICBzdWJncmFwaCBIeWJyaWRSZXRbIkh5YnJpZCByZXRyaWV2YWwiXQogICAgICAgIFJldHJpZXZlclsiR3JhcGhSZXRyaWV2ZXIoZ3JhcGgsIHJhZykiXTo6Omh5YnJpZCAtLT4gVmVjdG9yQ2h1bmtzWyJWZWN0b3IgY2h1bmtzIChyYWdsZWFwLXJhZykiXTo6Omh5YnJpZAogICAgICAgIFJldHJpZXZlciAtLT4gR3JhcGhDb250ZXh0WyJHcmFwaCBjb250ZXh0PGJyLz5yZWxhdGVkX2RvY3VtZW50cywgcmVsYXRlZF9lbnRpdGllcyJdOjo6aHlicmlkCiAgICAgICAgVmVjdG9yQ2h1bmtzIC0tPiBDb21iaW5lZFsiQ29tYmluZWQgcmVzdWx0PGJyLz5hbHJlYWR5X2luX3ZlY3Rvcl9yZXN1bHRzIGZsYWciXTo6Omh5YnJpZAogICAgICAgIEdyYXBoQ29udGV4dCAtLT4gQ29tYmluZWQKICAgIGVuZAo=" alt="ragleap-graph write/read/hybrid-retrieval architecture" width="100%">

## LLM-based extraction and dedup (v0.2.0+)

The default entity extraction is regex/heuristic-based (fast, free, zero
dependencies). For messier input — e.g. inconsistent capitalization like
"Acme Corp" vs "ACME Corp." — LLM-based extraction and dedup produce
cleaner graphs. Requires the `llm` extra: `pip install ragleap-graph[llm]`

```python
from ragleap.generation import ProviderConfig
from ragleap_graph import GraphConfig, GraphIndex, ExtractionConfig

graph = GraphIndex(
    config=GraphConfig(uri="bolt://localhost:7687", user="neo4j", password="..."),
    extraction=ExtractionConfig(
        method="llm",
        provider=ProviderConfig(provider="gemini", api_key="...", model="gemini-3.6-flash"),
        dedup_enabled=True,
    ),
)
```

Note: `EntityDeduplicator` merges spelling variants of an already-extracted
name; it does not fix fragmentation caused by the regex extractor splitting
one real-world entity into multiple candidates in the first place — see
CHANGELOG.md for a real, measured example of this and how `method="llm"`
avoids it at the source.

## Operations

`ragleap-graph` is a knowledge-graph retrieval library, not a database
administration tool. Backup and restore of the underlying Neo4j database
are explicitly the operator's responsibility, not something this library
wraps or automates -- see
[`docs/operations/backup-and-restore.md`](docs/operations/backup-and-restore.md)
for a concrete, tested procedure using Neo4j's native `neo4j-admin`
tooling, and
[`docs/adr/0001-backup-restore-ownership.md`](docs/adr/0001-backup-restore-ownership.md)
for the reasoning behind this scope decision.

## Status

v0.6.5. Ported from a real production `GraphService`, adapted for standalone open-source use — see `HANDOFF.md` for the full design history. `ragleap-rag` >=0.12.0 is an optional dependency, required only for `method="llm"`.

## License

MIT
