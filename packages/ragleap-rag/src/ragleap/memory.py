"""
Persistent conversation memory for ragleap-rag.
Session-scoped, Postgres-backed. Opt-in per call — pass session_id to
ask()/ask_stream() to get multi-turn context; omit it and behavior is
identical to a stateless call.
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

DEFAULT_MAX_HISTORY_MESSAGES = 10


class ConversationMemory:
    """Stores and retrieves per-session conversation history."""

    def __init__(self, database_url: str, max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES):
        self.database_url = database_url
        self.max_history_messages = max_history_messages

    def _get_connection(self):
        import psycopg2
        return psycopg2.connect(self.database_url)

    def _ensure_session(self, cur, session_id: str) -> None:
        cur.execute(
            """
            INSERT INTO conversations (session_id) VALUES (%s)
            ON CONFLICT (session_id) DO UPDATE SET updated_at = now()
            """,
            (session_id,),
        )

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """Store a single message (role: 'user' or 'assistant')."""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            self._ensure_session(cur, session_id)
            cur.execute(
                "INSERT INTO conversation_messages (session_id, role, content) VALUES (%s, %s, %s)",
                (session_id, role, content),
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

    def get_history(self, session_id: str, limit: int = None) -> List[Dict]:
        """
        Return recent messages for a session, oldest first, as
        [{"role": ..., "content": ..., "created_at": ...}, ...].
        """
        limit = limit if limit is not None else self.max_history_messages
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT role, content, created_at FROM conversation_messages
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
            cur.close()
            return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in reversed(rows)]
        finally:
            conn.close()

    def clear_session(self, session_id: str) -> None:
        """Delete a session and all its messages."""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM conversations WHERE session_id = %s", (session_id,))
            conn.commit()
            cur.close()
            logger.info(f"Cleared session '{session_id}'")
        finally:
            conn.close()

    def build_history_prompt(self, session_id: str) -> str:
        """Return prior turns formatted for injection into a prompt. Empty string if no history."""
        history = self.get_history(session_id)
        if not history:
            return ""
        lines = [f"{m['role'].capitalize()}: {m['content']}" for m in history]
        return "Previous conversation:\n" + "\n".join(lines) + "\n\n"
