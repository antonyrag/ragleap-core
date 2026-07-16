"""
Knowledge Graph Service for RagLeap Core.

Neo4j-backed entity extraction and graph traversal, layered on top of the
existing pgvector retrieval. Single-tenant: no workspace scoping needed,
all graph nodes belong to this one deployment.

Ported from RagLeap's production retrieval/graph_service.py — same entity
extraction heuristics and Cypher queries, with Django/multi-tenancy removed.
"""
import os
import re
import uuid
import logging
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

logger = logging.getLogger(__name__)

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

# Optional domain-specific terms to always treat as entities, even when
# lowercase (acronym/capitalization heuristics below won't catch these).
# Empty by default — set via DOMAIN_TERMS env var as a comma-separated list,

ENTITY_STOPWORDS = {
    "the", "this", "that", "with", "from", "what", "when", "where",
    "which", "about", "does", "tell", "built", "using", "uses", "used",
    "platform", "into", "for", "and", "are", "was", "were", "has", "have",
}
# e.g. DOMAIN_TERMS="quarterly report,customer churn,net promoter score"
DOMAIN_TERMS = [
    t.strip().lower()
    for t in os.environ.get("DOMAIN_TERMS", "").split(",")
    if t.strip()
]


class GraphService:
    """
    Neo4j knowledge graph service. Extracts entities from ingested document
    chunks, builds a co-occurrence graph, and supports entity-based document
    lookup and graph traversal for hybrid retrieval.

    If Neo4j isn't configured or reachable, all methods degrade gracefully
    (return empty results) rather than raising — graph search is an
    enhancement on top of vector search, not a hard dependency.
    """

    def __init__(self):
        self.driver = None
        if GraphDatabase and NEO4J_PASSWORD:
            try:
                self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
                logger.info("Neo4j driver initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Neo4j driver: {e}")
                self.driver = None
        else:
            logger.info("Neo4j not configured (NEO4J_PASSWORD unset) — graph features disabled")

    def close(self):
        if self.driver:
            self.driver.close()

    def _normalize_entity_name(self, raw_name: str) -> str:
        """Normalize extracted entity text into a stable graph key."""
        if not raw_name:
            return ""
        cleaned = re.sub(r"\s+", " ", raw_name).strip()
        return cleaned[:200]

    def _extract_entity_candidates_from_text(self, text: str, max_entities: int = 12) -> List[str]:
        """Lightweight, deterministic entity extraction from free text."""
        if not text:
            return []

        candidates: List[str] = []
        candidates.extend(re.findall(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)?\b", text))
        candidates.extend(re.findall(r"\b(?:[A-Z][a-z]{2,})(?:\s+[A-Z][a-z]{2,}){0,2}\b", text))
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9]{2,}\b", text):
            if token.lower() in ENTITY_STOPWORDS:
                continue
            if token[0].isupper() and (any(c.isdigit() for c in token) or not token[1:].islower()):
                candidates.append(token)

        text_lower = text.lower()
        for term in DOMAIN_TERMS:
            if term in text_lower:
                candidates.append(term)

        seen = set()
        final: List[str] = []
        for cand in candidates:
            normalized = self._normalize_entity_name(cand)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen or key in ENTITY_STOPWORDS:
                continue
            seen.add(key)
            final.append(normalized)
            if len(final) >= max_entities:
                break

        return final

    def extract_query_entities(self, query: str, max_entities: int = 10) -> List[str]:
        """Extract seed entities from a user query for graph traversal."""
        if not query:
            return []

        candidates: List[str] = []
        candidates.extend(re.findall(r'"([^"\n]{3,120})"', query))
        candidates.extend(re.findall(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)?\b", query))
        candidates.extend(re.findall(r"\b(?:[A-Z][a-z]{2,})(?:\s+[A-Z][a-z]{2,}){0,2}\b", query))

        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{3,}\b", query):
            if token.lower() in ENTITY_STOPWORDS:
                continue
            candidates.append(token)

        seen = set()
        result: List[str] = []
        for cand in candidates:
            normalized = self._normalize_entity_name(cand)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(normalized)
            if len(result) >= max_entities:
                break

        return result

    def upsert_document_graph(
        self,
        document_id: str,
        document_title: str,
        chunks: List[Dict[str, Any]],
        max_entities: int = 80,
        max_pairs: int = 150,
    ) -> Dict[str, Any]:
        """Index one document and its entities into Neo4j."""
        summary = {
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

            entities = self._extract_entity_candidates_from_text(text, max_entities=12)
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

        try:
            with self.driver.session() as session:
                session.run(
                    """
                    MERGE (d:Document {id: $document_id})
                    ON CREATE SET d.created_at = datetime(), d.title = $document_title
                    SET d.updated_at = datetime(), d.title = coalesce($document_title, d.title)
                    """,
                    document_id=str(document_id),
                    document_title=(document_title or "")[:500],
                )

                for entity_name, weight in top_entities:
                    session.run(
                        """
                        MERGE (e:Entity {name: $entity_name})
                        ON CREATE SET e.id = $entity_uuid, e.created_at = datetime()
                        SET e.updated_at = datetime()
                        WITH e
                        MATCH (d:Document {id: $document_id})
                        MERGE (d)-[r:CONTAINS]->(e)
                        ON CREATE SET r.weight = $weight, r.created_at = datetime()
                        ON MATCH SET r.weight = coalesce(r.weight, 0) + $weight, r.updated_at = datetime()
                        """,
                        entity_name=entity_name,
                        document_id=str(document_id),
                        entity_uuid=str(uuid.uuid4()),
                        weight=float(weight),
                    )

                for (a_name, b_name), weight in top_pairs:
                    session.run(
                        """
                        MATCH (a:Entity {name: $a_name})
                        MATCH (b:Entity {name: $b_name})
                        WHERE a.name <> b.name
                        MERGE (a)-[r:RELATED_TO]->(b)
                        ON CREATE SET r.weight = $weight, r.created_at = datetime()
                        ON MATCH SET r.weight = coalesce(r.weight, 0) + $weight, r.updated_at = datetime()
                        """,
                        a_name=a_name,
                        b_name=b_name,
                        weight=float(weight),
                    )

            summary["success"] = True
            summary["entities_indexed"] = len(top_entities)
            summary["relationships_indexed"] = len(top_pairs)
            return summary

        except Exception as e:
            logger.error(f"Document graph upsert error: {e}", exc_info=True)
            summary["error"] = str(e)
            return summary

    def find_documents_by_entities(self, entity_names: List[str], limit: int = 25) -> List[Dict[str, Any]]:
        """Retrieve graph-relevant documents connected to entity names."""
        if not self.driver:
            return []

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

        if not normalized:
            return []

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (e:Entity)<-[r:CONTAINS]-(d:Document)
                    WHERE toLower(e.name) IN $entity_names
                    RETURN d.id AS document_id,
                           coalesce(d.title, '') AS document_name,
                           count(DISTINCT e) AS matched_entities,
                           sum(coalesce(r.weight, 1.0)) AS graph_score,
                           collect(DISTINCT e.name)[0..10] AS matched_entity_names
                    ORDER BY matched_entities DESC, graph_score DESC
                    LIMIT $limit
                    """,
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

    def search_related_entities(self, entity_names: List[str], max_depth: int = 2, limit: int = 10) -> List[Dict]:
        """Find entities related to query entities via graph traversal."""
        if not self.driver:
            return []

        try:
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

            if not normalized:
                return []

            with self.driver.session() as session:
                query = """
                MATCH (start:Entity)
                WHERE toLower(start.name) IN $entity_names
                MATCH path = (start)-[*1..{max_depth}]-(related:Entity)
                RETURN DISTINCT related.id AS entity_id,
                       related.name AS entity_name,
                       type(relationships(path)[0]) AS relationship,
                       length(path) AS depth,
                       properties(related) AS properties
                ORDER BY depth ASC
                LIMIT $limit
                """.format(max_depth=max_depth)

                result = session.run(query, entity_names=normalized, limit=limit)

                entities = []
                for record in result:
                    entities.append({
                        "entity_id": record["entity_id"],
                        "entity_name": record["entity_name"],
                        "name": record["entity_name"],
                        "relationship": record["relationship"],
                        "depth": record["depth"],
                        "properties": dict(record["properties"]) if record["properties"] else {},
                    })
                return entities
        except Exception as e:
            logger.error(f"Graph search error: {e}", exc_info=True)
            return []

    def health_check(self) -> bool:
        if not self.driver:
            return False
        try:
            with self.driver.session() as session:
                result = session.run("RETURN 1 AS test")
                return result.single()["test"] == 1
        except Exception as e:
            logger.error(f"Neo4j health check failed: {e}")
            return False


graph_service = GraphService()
