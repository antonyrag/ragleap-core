"""
FAISS-backed vector storage for ragleap-rag. Local, in-process,
no API key, no external service - good for prototyping, small-to-
medium local datasets, or fully offline use.

Honest limitations, stated upfront (not discovered later):
- FAISS only stores vectors, not text/metadata. A SQLite sidecar
  (stdlib, no new dependency) stores document/chunk text and metadata.
- No native full-text search - supports_sparse() is False, and
  RagLeap.ask(hybrid=True) gracefully degrades to dense-only search
  against this backend.
- Metadata filtering is a post-filter: over-fetch candidates from
  FAISS, then filter by metadata in SQLite. This is less efficient
  than pgvector's indexed JSONB containment for very large datasets.
- Without persist_directory=, everything is in-memory and lost when
  the process exits - by design, not a bug, for the "no setup at all"
  use case. Pass persist_directory= for data that survives restarts.
"""
import json
import logging
import os
import sqlite3
import threading
import uuid
from typing import Dict, List, Optional

from ragleap.vectorstores.base import VectorBackend

logger = logging.getLogger(__name__)


class FAISSBackend(VectorBackend):
    def __init__(self, persist_directory: Optional[str] = None):
        try:
            import faiss  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "FAISSBackend requires the 'faiss' extra: pip install ragleap-rag[faiss]"
            ) from e

        self.persist_directory = persist_directory
        self._index = None
        self._dimensions = None
        self._lock = threading.Lock()

        if persist_directory:
            os.makedirs(persist_directory, exist_ok=True)
            self._sqlite_path = os.path.join(persist_directory, "faiss_meta.sqlite3")
            self._index_path = os.path.join(persist_directory, "faiss.index")
        else:
            self._sqlite_path = ":memory:"
            self._index_path = None

        self._conn = sqlite3.connect(self._sqlite_path, check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, metadata TEXT NOT NULL, uploaded_at TEXT NOT NULL
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS chunks (
                vid INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                document_name TEXT NOT NULL, chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL, token_count INTEGER, metadata TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def init_schema(self, dimensions: int) -> None:
        import faiss
        self._dimensions = dimensions
        with self._lock:
            if self._index_path and os.path.exists(self._index_path):
                self._index = faiss.read_index(self._index_path)
                logger.info(f"FAISSBackend: loaded existing index from {self._index_path}")
            else:
                self._index = faiss.IndexIDMap(faiss.IndexFlatIP(dimensions))
                logger.info(f"FAISSBackend: created new in-memory index (dimensions={dimensions})")

    def _save_index_if_persistent(self) -> None:
        if self._index_path:
            import faiss
            faiss.write_index(self._index, self._index_path)

    def _normalize(self, vec: List[float]):
        import numpy as np
        arr = np.array([vec], dtype="float32")
        import faiss
        faiss.normalize_L2(arr)
        return arr

    def insert_document(self, document_id: str, filename: str, metadata: Dict) -> None:
        import datetime
        with self._lock:
            self._conn.execute(
                "INSERT INTO documents (id, filename, metadata, uploaded_at) VALUES (?, ?, ?, ?)",
                (document_id, filename, json.dumps(metadata or {}), datetime.datetime.utcnow().isoformat()),
            )
            self._conn.commit()

    def insert_chunk(
        self, document_id: str, document_name: str, chunk_index: int,
        text: str, token_count: int, embedding: List[float], metadata: Dict,
    ) -> None:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO chunks (document_id, document_name, chunk_index, text, token_count, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (document_id, document_name, chunk_index, text, token_count, json.dumps(metadata or {})),
            )
            vid = cur.lastrowid
            self._conn.commit()

            import numpy as np
            vec = self._normalize(embedding)
            self._index.add_with_ids(vec, np.array([vid], dtype="int64"))
            self._save_index_if_persistent()

    def _metadata_matches(self, stored_json: str, metadata_filter: Optional[Dict]) -> bool:
        if not metadata_filter:
            return True
        stored = json.loads(stored_json)
        return all(stored.get(k) == v for k, v in metadata_filter.items())

    def search_dense(self, embedding: List[float], top_k: int, metadata_filter: Optional[Dict] = None) -> List[Dict]:
        if not embedding or self._index is None or self._index.ntotal == 0:
            return []
        if self._dimensions and len(embedding) != self._dimensions:
            logger.warning(f"Query embedding dim={len(embedding)} != expected {self._dimensions}; skipping search")
            return []

        fetch_k = top_k * 5 if metadata_filter else top_k
        fetch_k = min(fetch_k, self._index.ntotal)
        query = self._normalize(embedding)

        with self._lock:
            scores, ids = self._index.search(query, fetch_k)

        results = []
        for score, vid in zip(scores[0], ids[0]):
            if vid == -1:
                continue
            row = self._conn.execute(
                "SELECT document_id, document_name, chunk_index, text, metadata FROM chunks WHERE vid = ?",
                (int(vid),),
            ).fetchone()
            if row is None:
                continue
            document_id, document_name, chunk_index, text, metadata_json = row
            if not self._metadata_matches(metadata_json, metadata_filter):
                continue
            results.append({
                "chunk_id": str(vid), "text": text, "similarity_score": round(float(score), 4),
                "document_id": document_id, "document_name": document_name, "chunk_index": chunk_index,
            })
            if len(results) >= top_k:
                break
        return results

    def supports_sparse(self) -> bool:
        return False

    def list_documents(self, limit: int, offset: int) -> List[Dict]:
        rows = self._conn.execute(
            """SELECT d.id, d.filename, d.uploaded_at, d.metadata, COUNT(c.vid) AS chunk_count
               FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
               GROUP BY d.id ORDER BY d.uploaded_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return [
            {"document_id": r[0], "filename": r[1], "uploaded_at": r[2], "metadata": json.loads(r[3]), "chunk_count": r[4]}
            for r in rows
        ]

    def delete_document(self, document_id: str) -> bool:
        import numpy as np
        with self._lock:
            vids = [r[0] for r in self._conn.execute("SELECT vid FROM chunks WHERE document_id = ?", (document_id,)).fetchall()]
            if vids:
                self._index.remove_ids(np.array(vids, dtype="int64"))
            cur = self._conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            self._conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            deleted = cur.rowcount > 0
            self._conn.commit()
            self._save_index_if_persistent()
        return deleted

    def get_document_filename(self, document_id: str) -> Optional[str]:
        row = self._conn.execute("SELECT filename FROM documents WHERE id = ?", (document_id,)).fetchone()
        return row[0] if row else None
