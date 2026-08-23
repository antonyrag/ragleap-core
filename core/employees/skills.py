"""Read path: get_role_skills / get_role_personality / get_capability_summary."""
import logging

from core.employees import memory, roles
from core.employees.defaults import ROLE_SKILL_TAGS, DEFAULT_ROLES
from core.employees._db import get_connection

logger = logging.getLogger(__name__)


def get_role_skills(role: str = "general", query: str = None, top_k: int = 8) -> str:
    """
    Owner instructions are always pulled first and prepended, then
    excluded from the tag/semantic results below so they never appear
    twice in the same prompt.
    """
    owner_block = memory.get_owner_instructions()

    def _dedupe(entries):
        return [e for e in entries if "owner_instruction" not in (e.get("tags") or [])]

    tags = ROLE_SKILL_TAGS.get(role, ROLE_SKILL_TAGS["general"])
    if query and len(query.strip()) > 5:
        try:
            entries = _dedupe(memory.semantic_search(query, top_k))
            if entries:
                return memory.format_context(owner_block, entries)
        except Exception as e:
            logger.debug(f"Semantic search failed, falling back to tag search: {e}")
    entries = _dedupe(memory.tag_search(tags, top_k))
    return memory.format_context(owner_block, entries)


def get_role_skills_with_ids(role: str = "general", query: str = None, top_k: int = 8):
    """
    Same retrieval as get_role_skills(), but also returns the
    employee_memory row IDs that were actually used -- so a caller
    can later report back whether they led to a good outcome via
    core.employees.learning.record_role_memory_outcome().

    Returns (formatted_context: str, memory_ids: List[str]).
    """
    owner_block = memory.get_owner_instructions()

    def _dedupe(entries):
        return [e for e in entries if "owner_instruction" not in (e.get("tags") or [])]

    tags = ROLE_SKILL_TAGS.get(role, ROLE_SKILL_TAGS["general"])
    entries = []
    if query and len(query.strip()) > 5:
        try:
            entries = _dedupe(memory.semantic_search(query, top_k))
        except Exception as e:
            logger.debug(f"Semantic search failed, falling back to tag search: {e}")
    if not entries:
        entries = _dedupe(memory.tag_search(tags, top_k))
    text = memory.format_context(owner_block, entries)
    ids = [e["id"] for e in entries]
    return text, ids


def get_role_personality(role: str = "support") -> str:
    r = roles.get_role(role)
    if r and r.get("personality"):
        return r["personality"]
    for d in DEFAULT_ROLES:
        if d["role"] == role:
            return d["personality"]
    return ""


def get_capability_summary() -> str:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM documents")
        doc_count = cur.fetchone()[0]
        try:
            cur.execute("SELECT COUNT(*) FROM data_sources WHERE is_active = true")
            integration_count = cur.fetchone()[0]
        except Exception:
            integration_count = 0
        cur.execute("SELECT COUNT(*) FROM employee_memory WHERE tags ? 'interaction'")
        mem_count = cur.fetchone()[0]
        cur.close()
    except Exception as e:
        logger.debug(f"get_capability_summary error: {e}")
        return ""
    finally:
        conn.close()
    parts = []
    if doc_count:
        parts.append(f"{doc_count} knowledge document{'s' if doc_count != 1 else ''}")
    if integration_count:
        parts.append(f"{integration_count} active integration{'s' if integration_count != 1 else ''}")
    if mem_count:
        parts.append(f"{mem_count} learned interaction pattern{'s' if mem_count != 1 else ''}")
    if not parts:
        return ""
    return f"[Capabilities: {', '.join(parts)}]"
