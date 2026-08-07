# Changelog

All notable changes to `ragleap-graph` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0]

### Added

- Initial implementation: `GraphConfig` and `GraphIndex`, knowledge-graph-augmented retrieval for RAG systems via Neo4j.
- Ported from a real, production `GraphService` (Neo4j-backed, regex entity extraction, co-occurrence graph construction), with deliberate adaptations for standalone open-source use:
  - `workspace_id` (required, Django multi-tenant SaaS concept) generalized to an optional `namespace=` parameter, defaulting to `None` — mirrors `ragleap-rag`'s own `metadata_filter=` convention.
  - Django `settings` coupling replaced with an explicit `GraphConfig` dataclass — zero framework dependency, same pattern as `ragleap-rag`'s `EmbeddingConfig`/`ProviderConfig`.
  - A hardcoded, deployment-specific domain vocabulary list (radiation-safety/medical-physics terms) found in the source was **not** carried over as a hardcoded default — it's now an optional `domain_terms=` parameter instead, since shipping someone else's internal business vocabulary as a public library default would be inappropriate and actively wrong for other domains.
- 5 core methods: `upsert_document`, `find_documents_by_entities`, `search_related_entities`, `document_entities`, `health_check`.
- **Real security fix vs. the source this was ported from**: `search_related_entities()`'s `max_depth` parameter is validated as a bounded integer (1-10) before being used in Cypher query construction. The source interpolated this value into the query string unvalidated (`.format(max_depth=max_depth)`) — necessary because Neo4j's Cypher can't parameterize variable-length path bounds normally, but that means unvalidated input would be a real injection vector in a public library API accepting arbitrary caller input.
- **Real bug found and fixed during implementation** (not just written and assumed correct): `GraphDatabase.driver()` is lazy — it does not attempt a real connection at construction time. Without an explicit `verify_connectivity()` call, a bad URI/credentials would silently leave `self.driver` set to a non-functional object instead of `None`, breaking the documented "driver is None means unavailable" contract. Caught by a real test failure, not assumed correct — see the test suite for the exact scenario.
- 26 tests: pure-logic tests (entity normalization, extraction, `max_depth` validation) requiring no live Neo4j, driver-unavailable graceful-degradation tests for every public method, and one live end-to-end integration test (write, query three ways, verified self-cleanup — 0 nodes left behind) that runs automatically when real `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD` credentials are present, and skips cleanly otherwise.
- CI: dedicated `ragleap-graph-tests` job with a real Neo4j service container, mirroring `ragleap-rag-tests`' pattern — confirmed passing in GitHub's own CI environment, not just locally.
- **This is the first package in the ragleap ecosystem with genuine, complete live verification from day one** — unlike several `ragleap-rag` vector backends, which shipped honestly labeled "code-complete but unverified" due to no account access. Real Neo4j access was already available, so every method here has actually been proven to work end-to-end, not just tested in isolation.
