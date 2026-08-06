"""
ragleap-graph: knowledge-graph-augmented retrieval for RAG systems.

Ported from a real, production GraphService (Neo4j-backed, regex entity
extraction, co-occurrence graph construction) with two deliberate
adaptations for standalone open-source use:

1. `workspace_id` (required, Django multi-tenant SaaS concept) becomes
   an optional `namespace=` parameter, defaulting to None — mirrors
   ragleap-rag's own `metadata_filter=` convention.
2. Django `settings` coupling becomes an explicit `GraphConfig`
   dataclass — zero framework dependency, same pattern as ragleap-rag's
   `EmbeddingConfig`/`ProviderConfig`.

A real security fix vs. the source this was ported from: `max_depth` in
`search_related_entities()` is validated as a bounded integer before
being used in Cypher query construction (the underlying Neo4j
variable-length-path syntax can't be parameterized normally, so the
depth value has to be validated before string formatting, not just
trusted).
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

logger = logging.getLogger(__name__)

__version__ = "0.1.0"

# Hard ceiling on traversal depth — prevents both runaway queries and,
# since max_depth is string-interpolated into Cypher (see note above),
# guards against malformed/malicious input reaching the query text.
MAX_ALLOWED_DEPTH = 10


@dataclass
class GraphConfig:
    """Connection config for a Neo4j-backed GraphIndex.

    No framework dependency — pass values directly rather than relying
    on ambient settings (Django, env vars, etc.). Callers who want
    env-var-driven config can build one with `GraphConfig(uri=os.environ[...])`
    themselves.
    """
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = ""


class GraphIndex:
    """
    Neo4j-backed knowledge graph index for entity-augmented retrieval.

    Gracefully degrades if the `neo4j` package isn't installed or the
    driver can't connect — `self.driver` will be None and all query
    methods return empty results rather than raising, matching the
    behavior of the production service this was ported from. Always
    safe to construct; check `health_check()` if you need to confirm
    connectivity before relying on it.
    """

    def __init__(self, config: Optional[GraphConfig] = None):
        self.config = config or GraphConfig()
        self.driver = None

        if GraphDatabase is None:
            logger.warning(
                "neo4j package not installed. Install with: pip install ragleap-graph[neo4j] "
                "(or just `pip install neo4j`). Graph queries will be unavailable."
            )
            return

        try:
            self.driver = GraphDatabase.driver(
                self.config.uri,
                auth=(self.config.user, self.config.password),
            )
            # GraphDatabase.driver() is lazy - it does not attempt a real
            # connection until first use. Without an explicit check here,
            # a bad URI/credentials would silently leave self.driver set
            # to a non-functional object instead of None, breaking the
            # "always safe to construct, check driver is None" contract
            # documented on this class.
            self.driver.verify_connectivity()
            logger.info("Neo4j driver initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Neo4j driver: {e}")
            if self.driver is not None:
                try:
                    self.driver.close()
                except Exception:
                    pass
            self.driver = None

    def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self.driver:
            self.driver.close()

    def __enter__(self) -> "GraphIndex":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Entity extraction (regex/heuristic-based, not LLM-based — cheap
    # and deterministic, matching the production approach this was
    # ported from)
    # ------------------------------------------------------------------

    def _normalize_entity_name(self, raw_name: str) -> str:
        """Normalize extracted entity text into a stable graph key.

        Ported verbatim from the production implementation this package
        is based on (verified via direct source review).
        """
        if not raw_name:
            return ""
        name = re.sub(r"\s+", " ", str(raw_name)).strip(" \t\r\n.,;:!?()[]{}'\"")
        if len(name) < 3:
            return ""
        # Keep acronyms uppercase (e.g., ALARA, IAEA), title-case normal phrases.
        if name.isupper():
            normalized = name
        else:
            normalized = " ".join(part.capitalize() for part in name.split())
        if len(normalized) > 120:
            normalized = normalized[:120]
        return normalized

    def _extract_entity_candidates_from_text(
        self,
        text: str,
        max_entities: int = 12,
        domain_terms: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Lightweight, deterministic entity extraction from free text.

        Ported from the production implementation this package is based
        on, with one deliberate change: the source had a hardcoded list
        of domain-specific terms (radiation-safety/medical-physics
        vocabulary specific to that deployment's customer). That's not
        appropriate as a hardcoded default in a general-purpose
        open-source package — it would leak deployment-specific business
        context and be irrelevant (or actively wrong) for any other
        domain. Here, `domain_terms=` is an optional parameter instead —
        pass your own domain vocabulary if useful, or omit it entirely
        for fully generic acronym/capitalized-phrase extraction.
        """
        if not text:
            return []

        candidates: List[str] = []
        # 1) Acronyms and all-caps entities.
        candidates.extend(re.findall(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)?\b", text))
        # 2) Capitalized word sequences (person/org/concept-like phrases).
        candidates.extend(
            re.findall(r"\b(?:[A-Z][a-z]{2,})(?:\s+[A-Z][a-z]{2,}){0,2}\b", text)
        )
        # 3) Optional caller-supplied domain terms that may appear lowercase.
        if domain_terms:
            text_lower = text.lower()
            for term in domain_terms:
                if term.lower() in text_lower:
                    candidates.append(term)

        seen = set()
        final: List[str] = []
        for cand in candidates:
            normalized = self._normalize_entity_name(cand)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            final.append(normalized)
            if len(final) >= max_entities:
                break
        return final

    def extract_query_entities(
        self, query: str, max_entities: int = 10, domain_terms: Optional[List[str]] = None
    ) -> List[str]:
        """Extract entity candidates from a user query string."""
        return self._extract_entity_candidates_from_text(
            query, max_entities=max_entities, domain_terms=domain_terms
        )

    # ------------------------------------------------------------------
    # Core graph operations
    # ------------------------------------------------------------------

    def upsert_document(
        self,
        document_id: str,
        title: str,
        chunks: List[Dict[str, Any]],
        namespace: Optional[str] = None,
        max_entities: int = 80,
        max_pairs: int = 150,
        domain_terms: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Index one document and its extracted entities into Neo4j.

        Builds co-occurrence edges between entities found in the same
        chunk, weighted by how often each entity/pair appears across
        the document. Writes are idempotent (MERGE-based) — safe to
        re-run on the same document.

        `namespace=` is optional; omit it for a single global graph, or
        pass a tenant/project identifier to keep graphs isolated.

        `domain_terms=` is an optional list of lowercase-matchable terms
        specific to your content (e.g. industry jargon) that the default
        acronym/capitalized-phrase heuristic wouldn't catch on its own.

        Returns an indexing summary so callers can log/monitor coverage.
        """
        summary: Dict[str, Any] = {
            "success": False,
            "document_id": str(document_id),
            "entities_indexed": 0,
            "relationships_indexed": 0,
            "error": None,
        }

        if not self.driver:
            summary["error"] = "Neo4j driver not available"
            return summary

        entity_counter: Counter = Counter()
        pair_counter: Counter = Counter()

        for chunk in chunks or []:
            text = (chunk.get("text") or "").strip()
            if not text:
                continue

            entities = self._extract_entity_candidates_from_text(
                text, max_entities=12, domain_terms=domain_terms
            )
            if not entities:
                continue

            unique_entities = []
            seen_local = set()
            for ent in entities:
                key = ent.lower()
                if key in seen_local:
                    continue
                seen_local.add(key)
                unique_entities.append(ent)
                entity_counter[ent] += 1

            for i in range(len(unique_entities)):
                for j in range(i + 1, len(unique_entities)):
                    a, b = unique_entities[i], unique_entities[j]
                    if a == b:
                        continue
                    pair = tuple(sorted((a, b), key=lambda s: s.lower()))
                    pair_counter[pair] += 1

        top_entities = entity_counter.most_common(max_entities)
        top_pairs = pair_counter.most_common(max_pairs)
        ns = namespace or ""

        try:
            with self.driver.session() as session:
                session.run(
                    """
                    MERGE (d:Document {id: $document_id, namespace: $namespace})
                    ON CREATE SET d.created_at = datetime()
                    SET d.title = $title
                    """,
                    document_id=str(document_id),
                    namespace=ns,
                    title=title or "",
                )

                for entity_name, weight in top_entities:
                    session.run(
                        """
                        MATCH (d:Document {id: $document_id, namespace: $namespace})
                        MERGE (e:Entity {name: $name_lower, namespace: $namespace})
                        ON CREATE SET e.display_name = $name
                        MERGE (d)-[r:CONTAINS]->(e)
                        ON CREATE SET r.weight = $weight
                        ON MATCH SET r.weight = coalesce(r.weight, 0) + $weight
                        """,
                        document_id=str(document_id),
                        namespace=ns,
                        name_lower=entity_name.lower(),
                        name=entity_name,
                        weight=float(weight),
                    )
                    summary["entities_indexed"] += 1

                for (a, b), weight in top_pairs:
                    session.run(
                        """
                        MATCH (ea:Entity {name: $a, namespace: $namespace})
                        MATCH (eb:Entity {name: $b, namespace: $namespace})
                        MERGE (ea)-[r:CO_OCCURS_WITH]-(eb)
                        ON CREATE SET r.weight = $weight
                        ON MATCH SET r.weight = coalesce(r.weight, 0) + $weight
                        """,
                        a=a.lower(),
                        b=b.lower(),
                        namespace=ns,
                        weight=float(weight),
                    )
                    summary["relationships_indexed"] += 1

            summary["success"] = True
            return summary

        except Exception as e:
            logger.error(f"Graph upsert error: {e}", exc_info=True)
            summary["error"] = str(e)
            return summary

    def find_documents_by_entities(
        self,
        entity_names: List[str],
        namespace: Optional[str] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Retrieve documents connected to the given entity names, ranked
        by matched-entity count and summed edge weight."""
        if not self.driver:
            return []

        normalized = self._normalize_entity_list(entity_names)
        if not normalized:
            return []

        ns = namespace or ""

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (e:Entity)<-[r:CONTAINS]-(d:Document)
                    WHERE e.namespace = $namespace
                      AND d.namespace = $namespace
                      AND e.name IN $entity_names
                    RETURN d.id AS document_id,
                           coalesce(d.title, '') AS document_name,
                           count(DISTINCT e) AS matched_entities,
                           sum(coalesce(r.weight, 1.0)) AS graph_score,
                           collect(DISTINCT e.display_name)[0..10] AS matched_entity_names
                    ORDER BY matched_entities DESC, graph_score DESC
                    LIMIT $limit
                    """,
                    namespace=ns,
                    entity_names=normalized,
                    limit=max(1, int(limit)),
                )

                docs = []
                for row in result:
                    docs.append({
                        "document_id": str(row["document_id"]) if row["document_id"] is not None else "",
                        "document_name": row["document_name"] or "",
                        "matched_entities": int(row["matched_entities"] or 0),
                        "graph_score": float(row["graph_score"] or 0.0),
                        "matched_entity_names": list(row["matched_entity_names"] or []),
                    })
                return docs

        except Exception as e:
            logger.error(f"Graph document lookup error: {e}", exc_info=True)
            return []

    def search_related_entities(
        self,
        entity_names: List[str],
        namespace: Optional[str] = None,
        max_depth: int = 2,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Find entities related to the given entity names via graph
        traversal, up to `max_depth` hops.

        `max_depth` is validated as a bounded integer (1-10) before use
        — Neo4j's Cypher can't parameterize variable-length path bounds
        normally, so this value gets string-formatted into the query.
        Unvalidated input here would be a real injection vector.
        """
        # Validate first, regardless of driver state - invalid input is
        # invalid input whether or not Neo4j happens to be reachable.
        try:
            max_depth = int(max_depth)
        except (TypeError, ValueError):
            raise ValueError(f"max_depth must be an integer, got {max_depth!r}")
        if not (1 <= max_depth <= MAX_ALLOWED_DEPTH):
            raise ValueError(
                f"max_depth must be between 1 and {MAX_ALLOWED_DEPTH}, got {max_depth}"
            )

        if not self.driver:
            logger.warning("Neo4j driver not available")
            return []

        normalized = self._normalize_entity_list(entity_names)
        if not normalized:
            return []

        ns = namespace or ""

        try:
            with self.driver.session() as session:
                # max_depth is validated above (bounded int) before
                # being formatted in — Cypher variable-length path
                # bounds can't be passed as query parameters.
                query = """
                    MATCH (start:Entity)
                    WHERE start.name IN $entity_names
                      AND start.namespace = $namespace
                    MATCH path = (start)-[*1..{max_depth}]-(related:Entity)
                    WHERE related.namespace = $namespace
                    RETURN DISTINCT related.name AS entity_id,
                           related.display_name AS entity_name,
                           type(relationships(path)[0]) AS relationship,
                           length(path) AS depth
                    ORDER BY depth ASC
                    LIMIT $limit
                """.format(max_depth=max_depth)

                result = session.run(
                    query,
                    entity_names=normalized,
                    namespace=ns,
                    limit=max(1, int(limit)),
                )

                related = []
                for row in result:
                    related.append({
                        "entity_id": row["entity_id"],
                        "entity_name": row["entity_name"],
                        "relationship": row["relationship"],
                        "depth": int(row["depth"]),
                    })
                return related

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Related-entity search error: {e}", exc_info=True)
            return []

    def document_entities(
        self,
        document_id: str,
        namespace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find all entities linked to a specific document."""
        if not self.driver:
            logger.warning("Neo4j driver not available")
            return []

        ns = namespace or ""

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (d:Document {id: $document_id, namespace: $namespace})
                    MATCH (d)-[:CONTAINS]->(e:Entity)
                    RETURN e.name AS entity_id,
                           e.display_name AS entity_name
                    LIMIT 50
                    """,
                    document_id=str(document_id),
                    namespace=ns,
                )

                entities = []
                for row in result:
                    entities.append({
                        "entity_id": row["entity_id"],
                        "entity_name": row["entity_name"],
                    })
                return entities

        except Exception as e:
            logger.error(f"Document entity lookup error: {e}", exc_info=True)
            return []

    def health_check(self) -> bool:
        """Return True if the Neo4j driver is connected and responsive."""
        if not self.driver:
            return False
        try:
            with self.driver.session() as session:
                session.run("RETURN 1")
            return True
        except Exception as e:
            logger.warning(f"Graph health check failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_entity_list(self, entity_names: List[str]) -> List[str]:
        normalized = []
        seen = set()
        for name in entity_names or []:
            norm = self._normalize_entity_name(name)
            if not norm:
                continue
            key = norm.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(key)
        return normalized


__all__ = ["GraphConfig", "GraphIndex", "__version__"]
