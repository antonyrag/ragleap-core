"""
Single-tenant learned-memory store for AI Employees.
Same design as production's skill_context.py write path (dedupe by content
hash, importance-weighted, semantic + tag-fallback retrieval) but backed by
its own employee_memory table instead of the multi-tenant MemoryEntry system.
"""
import hashlib
import json
import logging
from typing import List, Dict, Optional

from core.embedding import EmbeddingService
from core.employees._db import get_connection

logger = logging.getLogger(__name__)


def write_learned_skill(text, tags, importance=0.7, source="interaction",
                         permanent=False, force_update=False) -> Optional[Dict]:
    if not text or len(text.strip()) < 10:
        return None
    content_hash = hashlib.md5(text[:200].encode()).hexdigest()[:8]
    conn = get_connection()
    try:
        cur = conn.cursor()
        if force_update:
            cur.execute("DELETE FROM employee_memory WHERE source = %s", (source,))
        embed_service = EmbeddingService()
        embedding = embed_service.embed_text(text)
        embedding_literal = (
            "[" + ",".join(str(float(x)) for x in embedding) + "]" if embedding else None
        )
        review_after_days = 365 if permanent else 180
        cur.execute(
            """
            INSERT INTO employee_memory
                (text_content, summary, tags, importance, source, permanent,
                 review_after_days, content_hash, embedding, token_count)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (content_hash, source) DO NOTHING
            RETURNING id, text_content, summary, tags, importance, created_at
            """,
            (text, text[:300], json.dumps(list(tags) + [f"source:{source}"]),
             importance if not permanent else max(importance, 0.95), source,
             permanent or importance >= 0.95, review_after_days, content_hash,
             embedding_literal, len(text.split())),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if row is None:
            return None
        return {"id": str(row[0]), "text_content": row[1], "summary": row[2],
                "tags": row[3], "importance": row[4], "created_at": row[5].isoformat()}
    except Exception as e:
        conn.rollback()
        logger.error(f"write_learned_skill error: {e}")
        return None
    finally:
        conn.close()


def reinforce_memories(ids: List[str], delta: float) -> int:
    """
    Nudge importance for specific memory entries based on a real
    outcome (positive delta = the memory contributed to a good
    outcome, negative = it did not). Clamped to [0.1, 1.0] so no
    single event can zero out or max out a memory permanently.
    Returns the number of rows updated.

    This is NOT model training -- no weights change. It is an
    adaptive importance signal layered on the existing retrieval
    system: entries that keep contributing to good outcomes surface
    more often, entries that do not gradually surface less.
    """
    if not ids:
        return 0
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE employee_memory
            SET importance = LEAST(1.0, GREATEST(0.1, importance + %s))
            WHERE id = ANY(%s::uuid[])
            """,
            (delta, ids),
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        return updated
    except Exception as e:
        conn.rollback()
        logger.error(f"reinforce_memories error: {e}")
        return 0
    finally:
        conn.close()


def get_owner_instructions() -> str:
    rows = tag_search(["owner_instruction"], top_k=3)
    if not rows:
        return ""
    lines = [r["text_content"][:300] for r in rows]
    return "=== OWNER INSTRUCTIONS (obey always) ===\n" + "\n".join(lines)


def semantic_search(query: str, top_k: int = 8) -> List[Dict]:
    try:
        embed_service = EmbeddingService()
        query_embedding = embed_service.embed_text(query)
    except Exception as e:
        logger.debug(f"Embedding unavailable for semantic search: {e}")
        return []
    if not query_embedding:
        return []
    literal = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, text_content, summary, tags, importance, created_at
            FROM employee_memory WHERE embedding IS NOT NULL
            ORDER BY embedding::halfvec(3072) <=> %s::halfvec(3072) LIMIT %s
            """,
            (literal, top_k),
        )
        rows = cur.fetchall()
        cur.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.error(f"semantic_search error: {e}")
        return []
    finally:
        conn.close()


def tag_search(tags: List[str], top_k: int = 8) -> List[Dict]:
    if not tags:
        return []
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, text_content, summary, tags, importance, created_at
            FROM employee_memory WHERE tags ?| %s::text[]
            ORDER BY importance DESC, created_at DESC LIMIT %s
            """,
            (list(tags), top_k),
        )
        rows = cur.fetchall()
        cur.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.error(f"tag_search error: {e}")
        return []
    finally:
        conn.close()


def format_context(owner_block: str, entries: List[Dict]) -> str:
    lines = []
    if owner_block:
        lines.append(owner_block)
    for e in entries:
        text = e.get("summary") or e.get("text_content")
        if text and "not yet completed" not in text:
            lines.append(text[:300])
    return "\n\n".join(lines)


def _row_to_dict(row) -> Dict:
    return {"id": str(row[0]), "text_content": row[1], "summary": row[2],
            "tags": row[3], "importance": row[4], "created_at": row[5].isoformat()}
