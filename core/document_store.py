"""
Document list and delete for the dashboard Documents tab. Plain SQL, same connection style as
core/ingest.py. Deleting a document removes its chunks too (ON DELETE CASCADE in db/schema.sql).
"""
import logging
import os
import uuid

logger = logging.getLogger(__name__)

MAX_LIMIT = 500


def _connect():
    import psycopg2
    return psycopg2.connect(
        os.environ.get("DATABASE_URL", "postgresql://ragleap:ragleap@localhost:5433/ragleap_core"))


def list_documents(limit: int = 100) -> list:
    limit = max(1, min(int(limit), MAX_LIMIT))
    conn = _connect()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT d.id, d.filename, d.uploaded_at, COUNT(c.id), d.source_grant, d.source_path "
                "FROM documents d LEFT JOIN chunks c ON c.document_id = d.id "
                "GROUP BY d.id, d.filename, d.uploaded_at, d.source_grant, d.source_path "
                "ORDER BY d.uploaded_at DESC LIMIT %s",
                (limit,))
            rows = cur.fetchall()
        except Exception as e:
            if e.__class__.__name__ != "UndefinedColumn":
                raise
            conn.rollback()      # the folder-ingest columns are not in this database yet
            cur.execute(
                "SELECT d.id, d.filename, d.uploaded_at, COUNT(c.id) "
                "FROM documents d LEFT JOIN chunks c ON c.document_id = d.id "
                "GROUP BY d.id, d.filename, d.uploaded_at ORDER BY d.uploaded_at DESC LIMIT %s",
                (limit,))
            rows = [tuple(r) + (None, None) for r in cur.fetchall()]
    finally:
        conn.close()
    return [{"id": str(r[0]), "filename": r[1], "uploaded_at": r[2].isoformat() if r[2] else None,
             "chunks": int(r[3]),
             "source": {"grant": r[4], "path": r[5]} if r[4] else None} for r in rows]


def delete_document(document_id: str) -> bool:
    """True when a document was deleted, False when no such document exists (or the id is malformed)."""
    try:
        uid = str(uuid.UUID(str(document_id)))
    except ValueError:
        return False
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM documents WHERE id = %s RETURNING id", (uid,))
        deleted = cur.fetchone() is not None
        conn.commit()
    finally:
        conn.close()
    return deleted


def delete_document_graph(document_id: str) -> str:
    """
    Clean the knowledge graph after a document was deleted. Returns "cleaned", "skipped" (graph not
    configured) or "failed". Never raises: the document is already gone from the database.
    """
    try:
        uid = str(uuid.UUID(str(document_id)))
        from core.graph import graph_service
        result = graph_service.delete_document_graph(uid)
    except Exception:
        logger.warning("Graph cleanup raised for document %s", document_id, exc_info=True)
        return "failed"
    if result.get("skipped"):
        return "skipped"
    return "cleaned" if result.get("success") else "failed"
