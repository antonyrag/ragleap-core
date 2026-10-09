# ragleap-graph (Java port)

Work in progress. Java port of the Python package packages/ragleap-graph (knowledge-graph-augmented retrieval for RAG).

Status: only the pure-logic slice exists so far (entity name normalization, regex entity extraction, composite key). Nothing here talks to Neo4j yet and the module is not published.

Parity: outputs are compared with fixtures generated from the real Python code at commit 226fa4de (see parity/gen_fixtures_a.py). The parity test is gated by RAGLEAP_GRAPH_PARITY_DIR and skipped when it is not set.
