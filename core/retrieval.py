"""
Vector Retrieval Service for RagLeap Core
Adapted from RagLeap's production pgvector cosine-distance search —
rewritten as plain SQL (psycopg2), no Django ORM, no multi-tenancy.
Supports dense (vector), sparse (Postgres full-text), and hybrid
(Reciprocal Rank Fusion of both) retrieval, optionally boosted by the
knowledge graph.
"""
import os
import logging
from typing import List, Dict, Optional

from core.graph import graph_service

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ragleap:ragleap@localhost:5432/ragleap_core")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "3072"))

# Reciprocal Rank Fusion constant. Higher = flatter weighting across ranks
# (top result matters relatively less vs. lower-ranked ones); 60 is the
# standard default used in the original RRF paper and most implementations.
RRF_K = int(os.environ.get("HYBRID_RRF_K", "60"))


class VectorRetrievalService:
    """
    Performs dense (pgvector), sparse (Postgres full-text), and hybrid
    search against a PostgreSQL 'chunks' table. Single-user,
    single-database — no workspace scoping needed.
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
        Dense retrieval: top_k most similar chunks to the query embedding,
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

    def search_sparse_chunks(
        self,
        query_text: str,
        top_k: int = 5,
        document_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Sparse (keyword/full-text) retrieval using Postgres's built-in
        text search: websearch_to_tsquery (handles quoted phrases, -exclusions,
        OR — the same syntax as a typical search engine query box) against
        the chunks.text_search_vector generated column, ranked by ts_rank.

        Returns the same dict shape as search_similar_chunks(), with
        similarity_score populated from the normalized ts_rank value.
        """
        if not query_text or not query_text.strip():
            return []

        sql = """
            SELECT
                id,
                text,
                document_id,
                document_name,
                chunk_index,
                ts_rank(text_search_vector, websearch_to_tsquery('english', %s)) AS rank_score
            FROM chunks
            WHERE text_search_vector @@ websearch_to_tsquery('english', %s)
        """
        params = [query_text, query_text]

        if document_id:
            sql += " AND document_id = %s"
            params.append(document_id)

        sql += " ORDER BY rank_score DESC LIMIT %s"
        params.append(top_k)

        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()
            conn.close()

            results = []
            for row in rows:
                chunk_id, text, doc_id, doc_name, chunk_index, rank_score = row
                results.append({
                    "chunk_id": str(chunk_id),
                    "text": text,
                    "similarity_score": round(float(rank_score), 4),
                    "document_id": str(doc_id),
                    "document_name": doc_name,
                    "chunk_index": chunk_index,
                })

            logger.info(f"Sparse search returned {len(results)} chunks (top_k={top_k})")
            return results

        except Exception as e:
            logger.error(f"Sparse search error: {e}", exc_info=True)
            raise

    def search_hybrid_chunks(
        self,
        query_text: str,
        query_embedding: List[float],
        top_k: int = 5,
        document_id: Optional[str] = None,
        use_graph: bool = True,
        graph_boost: float = 0.15,
    ) -> List[Dict]:
        """
        Hybrid retrieval: combines dense (vector) and sparse (full-text)
        results via Reciprocal Rank Fusion (RRF), then optionally applies
        the same knowledge-graph boost as search_similar_chunks_with_graph().

        RRF combines two differently-scaled ranking systems (cosine
        similarity vs. ts_rank) without needing fragile score
        normalization — each chunk's final score is based on its RANK
        in each list, not the raw scores, which is why it's a standard
        technique for combining dense+sparse retrieval.

        Note: similarity_score in the returned dicts is the RRF-fused
        score for this method, not a 0-1 cosine similarity — it's only
        meaningful for ranking within this result set, not comparable
        across calls to different search_* methods.
        """
        dense = self.search_similar_chunks(query_embedding, top_k=top_k * 3, document_id=document_id)
        sparse = self.search_sparse_chunks(query_text, top_k=top_k * 3, document_id=document_id)

        dense_ranks = {c["chunk_id"]: i for i, c in enumerate(dense)}
        sparse_ranks = {c["chunk_id"]: i for i, c in enumerate(sparse)}

        chunk_lookup: Dict[str, Dict] = {c["chunk_id"]: c for c in dense}
        for c in sparse:
            chunk_lookup.setdefault(c["chunk_id"], c)

        all_ids = set(dense_ranks) | set(sparse_ranks)
        if not all_ids:
            return []

        rrf_scores = {}
        for cid in all_ids:
            score = 0.0
            if cid in dense_ranks:
                score += 1.0 / (RRF_K + dense_ranks[cid] + 1)
            if cid in sparse_ranks:
                score += 1.0 / (RRF_K + sparse_ranks[cid] + 1)
            rrf_scores[cid] = score

        results = [dict(chunk_lookup[cid]) for cid in all_ids]
        for c in results:
            c["similarity_score"] = round(rrf_scores[c["chunk_id"]], 6)
            c["retrieval_method"] = "hybrid_rrf"

        results.sort(key=lambda c: c["similarity_score"], reverse=True)

        if use_graph:
            try:
                entities = graph_service.extract_query_entities(query_text)
                linked_doc_ids = set()
                if entities:
                    linked_docs = graph_service.find_documents_by_entities(entities)
                    linked_doc_ids = {d["document_id"] for d in linked_docs} if linked_docs else set()
                for c in results:
                    if c["document_id"] in linked_doc_ids:
                        c["similarity_score"] += graph_boost
                        c["graph_boosted"] = True
                results.sort(key=lambda c: c["similarity_score"], reverse=True)
            except Exception as e:
                logger.warning(f"Graph lookup failed during hybrid retrieval (non-fatal): {e}")

        logger.info(
            f"Hybrid search: {len(dense)} dense + {len(sparse)} sparse -> "
            f"{len(results)} fused, returning top {min(top_k, len(results))}"
        )
        return results[:top_k]

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

        Kept for backward compatibility — search_hybrid_chunks() is the
        recommended method going forward, since it includes this same
        graph boost plus sparse retrieval.
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
