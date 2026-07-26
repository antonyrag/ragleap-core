"""
Postgres + pgvector backend - the default, battle-tested storage for
ragleap-rag. This relocates the existing proven SQL from schema.py/
retrieval.py/__init__.py behind the VectorBackend interface rather
than rewriting the logic, to keep regression risk near zero.
"""
import json
import logging
from typing import Dict, List, Optional

from ragleap.vectorstores.base import VectorBackend
from ragleap.db import ConnectionPool
from ragleap import schema as _schema

logger = logging.getLogger(__name__)

RRF_K = 60


class PgVectorBackend(VectorBackend):
    def __init__(self, database_url: str, min_similarity: float = 0.05):
        self.database_url = database_url
        self.min_similarity = min_similarity
        self._pool = ConnectionPool(database_url)
        self._dimensions = None

    def init_schema(self, dimensions: int) -> None:
        self._dimensions = dimensions
        _schema.init_core_schema(self.database_url, dimensions=dimensions)

    def insert_document(self, document_id: str, filename: str, metadata: Dict) -> None:
        with self._pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO documents (id, filename, metadata) VALUES (%s, %s, %s::jsonb)",
                (document_id, filename, json.dumps(metadata or {})),
            )
            conn.commit()
            cur.close()

    def insert_chunk(
        self, document_id: str, document_name: str, chunk_index: int,
        text: str, token_count: int, embedding: List[float], metadata: Dict,
    ) -> None:
        embedding_literal = "[" + ",".join(str(float(x)) for x in embedding) + "]"
        with self._pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO chunks (document_id, document_name, chunk_index, text, token_count, embedding, metadata)
                VALUES (%s, %s, %s, %s, %s, %s::vector, %s::jsonb)
                """,
                (document_id, document_name, chunk_index, text, token_count, embedding_literal, json.dumps(metadata or {})),
            )
            conn.commit()
            cur.close()

    def search_dense(self, embedding: List[float], top_k: int, metadata_filter: Optional[Dict] = None) -> List[Dict]:
        if not embedding:
            return []
        dims = self._dimensions or len(embedding)
        literal = "[" + ",".join(str(float(x)) for x in embedding) + "]"

        sql = """
            SELECT id, text, document_id, document_name, chunk_index,
                   1 - (embedding::halfvec(%s) <=> %s::halfvec(%s)) / 2 AS similarity_score
            FROM chunks
        """
        params = [dims, literal, dims]
        where = []
        if metadata_filter:
            where.append("metadata @> %s::jsonb")
            params.append(json.dumps(metadata_filter))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY embedding::halfvec(%s) <=> %s::halfvec(%s) LIMIT %s"
        params.extend([dims, literal, dims, top_k])

        with self._pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()

        results = []
        for chunk_id, text, doc_id, doc_name, chunk_index, score in rows:
            if score < self.min_similarity:
                continue
            results.append({
                "chunk_id": str(chunk_id), "text": text,
                "similarity_score": round(float(score), 4),
                "document_id": str(doc_id), "document_name": doc_name, "chunk_index": chunk_index,
            })
        return results

    def search_sparse(self, query_text: str, top_k: int, metadata_filter: Optional[Dict] = None) -> List[Dict]:
        if not query_text or not query_text.strip():
            return []
        sql = """
            SELECT id, text, document_id, document_name, chunk_index,
                   ts_rank(text_search_vector, websearch_to_tsquery('english', %s)) AS rank_score
            FROM chunks
            WHERE text_search_vector @@ websearch_to_tsquery('english', %s)
        """
        params = [query_text, query_text]
        if metadata_filter:
            sql += " AND metadata @> %s::jsonb"
            params.append(json.dumps(metadata_filter))
        sql += " ORDER BY rank_score DESC LIMIT %s"
        params.append(top_k)

        with self._pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()

        return [
            {"chunk_id": str(r[0]), "text": r[1], "similarity_score": round(float(r[5]), 4),
             "document_id": str(r[2]), "document_name": r[3], "chunk_index": r[4]}
            for r in rows
        ]

    def search_hybrid(self, query_text: str, embedding: List[float], top_k: int, metadata_filter: Optional[Dict] = None) -> List[Dict]:
        dense = self.search_dense(embedding, top_k * 3, metadata_filter)
        sparse = self.search_sparse(query_text, top_k * 3, metadata_filter)

        dense_ranks = {c["chunk_id"]: i for i, c in enumerate(dense)}
        sparse_ranks = {c["chunk_id"]: i for i, c in enumerate(sparse)}
        lookup = {c["chunk_id"]: c for c in dense}
        for c in sparse:
            lookup.setdefault(c["chunk_id"], c)

        all_ids = set(dense_ranks) | set(sparse_ranks)
        if not all_ids:
            return []

        scores = {}
        for cid in all_ids:
            s = 0.0
            if cid in dense_ranks:
                s += 1.0 / (RRF_K + dense_ranks[cid] + 1)
            if cid in sparse_ranks:
                s += 1.0 / (RRF_K + sparse_ranks[cid] + 1)
            scores[cid] = s

        results = [dict(lookup[cid]) for cid in all_ids]
        for c in results:
            c["similarity_score"] = round(scores[c["chunk_id"]], 6)
            c["retrieval_method"] = "hybrid_rrf"
        results.sort(key=lambda c: c["similarity_score"], reverse=True)
        return results[:top_k]

    def supports_sparse(self) -> bool:
        return True

    def list_documents(self, limit: int, offset: int) -> List[Dict]:
        with self._pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT d.id, d.filename, d.uploaded_at, d.metadata, COUNT(c.id) AS chunk_count
                FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
                GROUP BY d.id, d.filename, d.uploaded_at, d.metadata
                ORDER BY d.uploaded_at DESC LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
            cur.close()
        return [
            {"document_id": str(r[0]), "filename": r[1], "uploaded_at": r[2], "metadata": r[3], "chunk_count": r[4]}
            for r in rows
        ]

    def delete_document(self, document_id: str) -> bool:
        with self._pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            cur.close()
        return deleted

    def get_document_filename(self, document_id: str) -> Optional[str]:
        with self._pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT filename FROM documents WHERE id = %s", (document_id,))
            row = cur.fetchone()
            cur.close()
        return row[0] if row else None
