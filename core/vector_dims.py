"""Keep the pgvector columns and HNSW indexes in step with the configured embedding size."""
import logging
from typing import Dict, List, Optional

from core.employees._db import get_connection

logger = logging.getLogger(__name__)
MAX_HNSW_HALFVEC_DIMS = 4000
TARGETS = [("chunks", "embedding", "chunks_embedding_idx"),
           ("employee_memory", "embedding", "employee_memory_embedding_idx")]


def column_dims(cur, table: str, column: str) -> Optional[int]:
    cur.execute("SELECT a.atttypmod FROM pg_attribute a WHERE a.attrelid = %s::regclass "
                "AND a.attname = %s AND NOT a.attisdropped", (table, column))
    row = cur.fetchone()
    return int(row[0]) if row and row[0] and row[0] > 0 else None


def ensure_table(conn, table: str, column: str, index: str, dims: int) -> Dict:
    dims = int(dims)
    if not 1 <= dims <= 16000:
        return {"table": table, "status": "invalid", "want": dims}
    cur = conn.cursor()
    try:
        try:
            have = column_dims(cur, table, column)
        except Exception:
            conn.rollback()
            return {"table": table, "status": "missing"}
        if have is None:
            return {"table": table, "status": "missing"}
        if have == dims:
            return {"table": table, "status": "ok", "dims": dims}
        cur.execute(f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL")
        rows = int(cur.fetchone()[0])
        if rows:
            return {"table": table, "status": "mismatch", "have": have, "want": dims, "rows": rows}
        cur.execute(f"DROP INDEX IF EXISTS {index}")
        cur.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE vector({dims})")
        if dims <= MAX_HNSW_HALFVEC_DIMS:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {index} ON {table} "
                        f"USING hnsw (({column}::halfvec({dims})) halfvec_cosine_ops)")
        else:
            logger.warning("No HNSW index on %s: %s dims is above the %s limit", table, dims, MAX_HNSW_HALFVEC_DIMS)
        conn.commit()
        return {"table": table, "status": "adjusted", "have": have, "want": dims}
    finally:
        cur.close()


def ensure_all(dims: int) -> List[Dict]:
    """Called once at startup. Never raises."""
    results: List[Dict] = []
    try:
        conn = get_connection()
        try:
            for table, column, index in TARGETS:
                r = ensure_table(conn, table, column, index, dims)
                if r["status"] == "mismatch":
                    logger.error("Embedding size mismatch on %s: column is %s but EMBEDDING_DIMENSIONS is %s and "
                                 "%s rows already hold embeddings. Re-ingest after clearing them, or switch back.",
                                 table, r["have"], r["want"], r["rows"])
                elif r["status"] == "adjusted":
                    logger.info("Resized %s.%s from %s to %s dimensions", table, column, r["have"], r["want"])
                results.append(r)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Vector size check skipped: %s", type(e).__name__)
    return results


def status(dims: int) -> List[Dict]:
    """Read-only: how each embedding column compares with the configured size. Changes nothing."""
    dims = int(dims)
    out: List[Dict] = []
    try:
        conn = get_connection()
    except Exception as e:
        logger.warning("Vector size status unavailable: %s", type(e).__name__)
        return out
    try:
        cur = conn.cursor()
        for table, column, _index in TARGETS:
            try:
                have = column_dims(cur, table, column)
                rows = 0
                if have is not None:
                    cur.execute(f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL")
                    rows = int(cur.fetchone()[0])
            except Exception:
                conn.rollback()
                out.append({"table": table, "status": "missing", "have": None, "want": dims, "rows": 0})
                continue
            if have is None:
                state = "missing"
            elif have == dims:
                state = "ok"
            elif rows:
                state = "mismatch"
            else:
                state = "will_resize"
            out.append({"table": table, "status": state, "have": have, "want": dims, "rows": rows})
        cur.close()
    finally:
        conn.close()
    return out
