"""
Retrieval for ragleap-rag: dense (pgvector), sparse (Postgres full-text),
and hybrid (Reciprocal Rank Fusion) search.

Requires a PostgreSQL database with the pgvector extension and the
schema created by ragleap.schema.init_schema() (or your own compatible
schema — see that module for the exact DDL).

No knowledge-graph coupling here by design — ragleap-graph (a separate
package) extends retrieval with graph-boosted ranking on top of this.
"""
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

RRF_K = 60  # Reciprocal Rank Fusion constant — 60 is the standard default.


class VectorRetrievalService:
    """
    Performs dense, sparse, and hybrid search against a PostgreSQL
    'chunks' table (see ragleap.schema for the required DDL).
    """

    def __init__(self, database_url: str, embedding_dimensions: int = 3072, min_similarity: float = 0.05):
        self.database_url = database_url
        self.embedding_dimensions = embedding_dimensions
        self.min_similarity = min_similarity

    def _get_connection(self):
        import psycopg2
        return psycopg2.connect(self.database_url)

    def search_similar_chunks(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        document_id: Optional[str] = None,
    ) -> List[Dict]:
        """Dense retrieval via pgvector cosine distance."""
        if not query_embedding:
            return []

        if len(query_embedding) != self.embedding_dimensions:
            logger.warning(
                f"Query embedding dim={len(query_embedding)} != expected {self.embedding_dimensions}; skipping search"
            )
            return []

        literal = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"

        sql = """
            SELECT
                id, text, document_id, document_name, chunk_index,
                1 - (embedding::halfvec(%s) <=> %s::halfvec(%s)) / 2 AS similarity_score
            FROM chunks
        """
        params = [self.embedding_dimensions, literal, self.embedding_dimensions]

        if document_id:
            sql += " WHERE document_id = %s"
            params.append(document_id)

        sql += " ORDER BY embedding::halfvec(%s) <=> %s::halfvec(%s) LIMIT %s"
        params.extend([self.embedding_dimensions, literal, self.embedding_dimensions, top_k])

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
        """Sparse (keyword/full-text) retrieval via Postgres text search."""
        if not query_text or not query_text.strip():
            return []

        sql = """
            SELECT id, text, document_id, document_name, chunk_index,
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
    ) -> List[Dict]:
        """
        Combines dense + sparse via Reciprocal Rank Fusion. similarity_score
        in the returned dicts is the RRF-fused score, meaningful only for
        ranking within this result set (not a 0-1 cosine similarity).
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

        logger.info(
            f"Hybrid search: {len(dense)} dense + {len(sparse)} sparse -> "
            f"{len(results)} fused, returning top {min(top_k, len(results))}"
        )
        return results[:top_k]
