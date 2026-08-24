"""
Real outcome signal for outcome-weighted memory: tracks the last
role-based reply per (channel, chat_id) so an owner can send a quick
feedback command afterward (thumbs up/down, "helpful"/"not helpful")
that gets attributed to the correct employee_memory entries via
core.employees.learning.record_role_memory_outcome().

Without this, there is no genuine success/failure signal available in
WhatsApp/Telegram/Discord/Voice -- this module is what makes the
outcome-weighted memory mechanism (see memory.reinforce_memories)
actually meaningful for real conversations, not just test calls.
"""
import json
import logging
from typing import List, Optional

from core.employees._db import get_connection

logger = logging.getLogger(__name__)

POSITIVE_COMMANDS = {"👍", "helpful", "that helped", "good answer", "thanks that worked"}
NEGATIVE_COMMANDS = {"👎", "not helpful", "that didn't help", "wrong answer", "bad answer"}


def record_last_reply(channel: str, chat_id: str, role_memory_ids: List[str]) -> None:
    """
    Call this right after sending a role-based reply, so a subsequent
    feedback command from the same chat can be attributed correctly.
    No-op if role_memory_ids is empty (no role was set, or nothing was
    retrieved) -- nothing meaningful to attribute feedback to.
    """
    if not role_memory_ids:
        return
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO role_reply_log (channel, chat_id, role_memory_ids, created_at)
            VALUES (%s, %s, %s::jsonb, now())
            ON CONFLICT (channel, chat_id)
            DO UPDATE SET role_memory_ids = EXCLUDED.role_memory_ids, created_at = now()
            """,
            (channel, chat_id, json.dumps(role_memory_ids)),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"record_last_reply error: {e}")
    finally:
        conn.close()


def get_last_reply(channel: str, chat_id: str) -> List[str]:
    """Returns the role_memory_ids from the most recent reply in this chat, or []."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT role_memory_ids FROM role_reply_log WHERE channel = %s AND chat_id = %s",
            (channel, chat_id),
        )
        row = cur.fetchone()
        cur.close()
        return row[0] if row else []
    except Exception as e:
        logger.error(f"get_last_reply error: {e}")
        return []
    finally:
        conn.close()


def detect_feedback_command(message: str) -> Optional[bool]:
    """
    Returns True if the message is a positive feedback command, False if
    negative, None if it's not a feedback command at all (i.e. treat it
    as a normal question).
    """
    if not message:
        return None
    normalized = message.strip().lower()
    if normalized in POSITIVE_COMMANDS:
        return True
    if normalized in NEGATIVE_COMMANDS:
        return False
    return None
