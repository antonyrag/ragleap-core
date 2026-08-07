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

## Status

Early alpha (v0.1.0). Ported from a real production `GraphService`, adapted for standalone open-source use — see `HANDOFF.md` for the full design history.

## License

MIT
