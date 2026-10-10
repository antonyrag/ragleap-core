# ragleap-graph (Java port)

Work in progress. Java port of the Python package packages/ragleap-graph (knowledge-graph-augmented retrieval for RAG).

Status: entity name normalization, regex entity extraction, composite key, and the Neo4j write path (upsertDocument, findDocumentsByEntities, documentEntities, searchRelatedEntities, findRelations, findLineage, findEntitiesByType) over the HTTP Query API exist so far; the module is not published. Live tests need NEO4J_HTTP_URL, NEO4J_USER and NEO4J_PASSWORD (a Neo4j server with the HTTP Query API; only Neo4j 5.26 Community has been tested) and skip when they are not set.

Parity: outputs are compared with fixtures generated from the real Python code at commit 226fa4de (see parity/gen_fixtures_a.py). The parity test is gated by RAGLEAP_GRAPH_PARITY_DIR and skipped when it is not set.
