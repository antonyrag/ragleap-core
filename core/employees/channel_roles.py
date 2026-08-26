"""
Owner-configurable default role per channel, plus a deterministic
intent-based override for a safe subset of customer-facing roles.

Design choice, stated plainly: automatic intent detection is
deliberately scoped to roles already marked customer-facing in their
own DEFAULT_ROLES channels config (support, sales, marketing) -- not
extended to manager/ceo/hr/finance/operations/secretary, which carry
internal business context (owner instructions, approval workflows,
strategic info) that shouldn't be exposed to an arbitrary inbound
message just because it happened to match a keyword. The owner can
still explicitly assign any of the 9 roles as a channel's default via
set_channel_role() -- that's a deliberate choice, not something
triggered by untrusted text.

This is the routing layer, not the role-creation layer: custom roles
can already be created via PATCH /employees/{role} (see
core/employees/roles.py::upsert_role) -- this module decides which
role a given message actually reaches, which was the real missing
piece, not the ability to define new roles.
"""
import logging
from typing import Optional

from core.employees._db import get_connection

logger = logging.getLogger(__name__)

DEFAULT_ROLE = "support"

# Roles safe for automatic intent-based routing -- customer-facing only.
INTENT_SAFE_ROLES = {"support", "sales", "marketing"}

INTENT_KEYWORDS = {
    "sales": {"price", "pricing", "buy", "purchase", "demo", "quote", "discount", "plan"},
    "marketing": {"campaign", "promotion", "newsletter", "partnership", "collaborate"},
}


def get_channel_role(channel: str) -> str:
    """Owner-configured default role for this channel, or 'support' if unset."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT role FROM channel_role_config WHERE channel = %s", (channel,))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else DEFAULT_ROLE
    except Exception as e:
        logger.error(f"get_channel_role error: {e}")
        return DEFAULT_ROLE
    finally:
        conn.close()


def set_channel_role(channel: str, role: str) -> bool:
    """Owner explicitly assigns a default role to a channel. Any of the 9 roles allowed here."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO channel_role_config (channel, role, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (channel) DO UPDATE SET role = EXCLUDED.role, updated_at = now()
            """,
            (channel, role),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"set_channel_role error: {e}")
        return False
    finally:
        conn.close()


def detect_intent_role(message: str) -> Optional[str]:
    """
    Deterministic keyword match against a safe subset of customer-facing
    roles only (see INTENT_SAFE_ROLES). Returns None if no strong match --
    caller should fall back to the channel's configured default role.
    """
    if not message:
        return None
    normalized = message.strip().lower()
    for role, keywords in INTENT_KEYWORDS.items():
        if role not in INTENT_SAFE_ROLES:
            continue
        if any(kw in normalized for kw in keywords):
            return role
    return None


def resolve_role(channel: str, message: str) -> str:
    """
    The actual routing decision a channel handler should use: an intent
    match (safe roles only) takes priority, otherwise the channel's
    configured default, otherwise 'support'.
    """
    intent_role = detect_intent_role(message)
    if intent_role:
        return intent_role
    return get_channel_role(channel)
