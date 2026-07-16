"""
Vector Retrieval Service for RagLeap Core
Adapted from RagLeap's production pgvector cosine-distance search —
rewritten as plain SQL (psycopg2), no Django ORM, no multi-tenancy.
Optionally boosted by the knowledge graph when available.
"""
import os
import logging
from typing import List, Dict, Optional

from core.graph import graph_service

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ragleap:ragleap@localhost:5432/ragleap_core")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "3072"))


class VectorRetrievalService:
    """
    Performs cosine-similarity vector search against a PostgreSQL + pgvector
    'chunks' table. Single-user, single-database — no workspace scoping needed.
    """

    def __init__(self, min_similarity: float = 0.05):
        self.min_similarity = min_similarity

    def _get_connection(self):
        import psycopg2
        return psycopg2.connect(DATABASE_URL)

    def search_similar_chunks(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        document_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Search for the top_k most similar chunks to the query embedding,
        using pgvector cosine distance (<=> operator).

        Returns a list of dicts: chunk_id, text, similarity_score,
        document_id, document_name, chunk_index.
        """
        if not query_embedding:
            return []

        if len(query_embedding) != EMBEDDING_DIMENSIONS:
            logger.warning(
                f"Query embedding dim={len(query_embedding)} != expected {EMBEDDING_DIMENSIONS}; skipping search"
            )
            return []

        literal = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"

        sql = """
            SELECT
                id,
                text,
                document_id,
                document_name,
                chunk_index,
                1 - (embedding::halfvec(3072) <=> %s::halfvec(3072)) / 2 AS similarity_score
            FROM chunks
        """
        params = [literal]

        if document_id:
            sql += " WHERE document_id = %s"
            params.append(document_id)

        sql += " ORDER BY embedding::halfvec(3072) <=> %s::halfvec(3072) LIMIT %s"
        params.extend([literal, top_k])

        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()
            conn.close()

            results = []
            for row in rows:
                chunk_id, text, doc_id, doc_name, chunk_index, similarity_score = row
                if similarity_score < self.min_similarity:
                    continue
                results.append({
                    "chunk_id": str(chunk_id),
                    "text": text,
                    "similarity_score": round(float(similarity_score), 4),
                    "document_id": str(doc_id),
                    "document_name": doc_name,
                    "chunk_index": chunk_index,
                })

            logger.info(f"Vector search returned {len(results)} chunks (top_k={top_k})")
            return results

        except Exception as e:
            logger.error(f"Vector search error: {e}", exc_info=True)
            raise

    def search_similar_chunks_with_graph(
        self,
        query_text: str,
        query_embedding: List[float],
        top_k: int = 5,
        document_id: Optional[str] = None,
        graph_boost: float = 0.15,
    ) -> List[Dict]:
        """
        Vector search, then boost chunks whose document is linked via the
        knowledge graph to entities mentioned in the query. Falls back to
        pure vector search if the graph is unavailable or finds nothing.
        """
        candidates = self.search_similar_chunks(
            query_embedding, top_k=top_k * 3, document_id=document_id
        )
        if not candidates:
            return []

        try:
            entities = graph_service.extract_query_entities(query_text)
            linked_doc_ids = set()
            if entities:
                linked_docs = graph_service.find_documents_by_entities(entities)
                linked_doc_ids = {d["document_id"] for d in linked_docs} if linked_docs else set()
        except Exception as e:
            logger.warning(f"Graph lookup failed during retrieval (non-fatal): {e}")
            linked_doc_ids = set()

        for chunk in candidates:
            if chunk["document_id"] in linked_doc_ids:
                chunk["similarity_score"] = min(1.0, chunk["similarity_score"] + graph_boost)
                chunk["graph_boosted"] = True

        candidates.sort(key=lambda c: c["similarity_score"], reverse=True)
        return candidates[:top_k]
