"""Business profile — single row per deployment. Ported from WorkspaceBusinessProfile."""
import json
import logging
from datetime import datetime
from typing import Dict

from core.employees._db import get_connection

logger = logging.getLogger(__name__)

_COLUMNS = [
    "business_name", "industry", "description", "products_services",
    "target_customers", "working_hours", "location", "tone_preference",
    "primary_language", "additional_languages", "owner_instructions",
    "auto_learned_profile", "skill_version", "is_profile_complete",
    "last_learned_at",
]


def get_profile() -> Dict:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT id, {', '.join(_COLUMNS)}, created_at, updated_at FROM business_profile LIMIT 1")
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO business_profile DEFAULT VALUES RETURNING id")
            new_id = cur.fetchone()[0]
            conn.commit()
            cur.execute(
                f"SELECT id, {', '.join(_COLUMNS)}, created_at, updated_at FROM business_profile WHERE id = %s",
                (new_id,),
            )
            row = cur.fetchone()
        cur.close()
        return _row_to_dict(row)
    finally:
        conn.close()


def update_profile(**fields) -> Dict:
    allowed = {
        "business_name", "industry", "description", "products_services",
        "target_customers", "working_hours", "location", "tone_preference",
        "primary_language", "additional_languages", "owner_instructions",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_profile()
    profile = get_profile()
    set_clauses, params = [], []
    for k, v in updates.items():
        if k == "additional_languages":
            set_clauses.append(f"{k} = %s::jsonb")
            params.append(json.dumps(v))
        else:
            set_clauses.append(f"{k} = %s")
            params.append(v)
    set_clauses.append("updated_at = now()")
    params.append(profile["id"])
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE business_profile SET {', '.join(set_clauses)} WHERE id = %s", params)
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_profile()


def save_auto_learned(text: str) -> Dict:
    profile = get_profile()
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE business_profile
            SET auto_learned_profile = %s, skill_version = skill_version + 1,
                last_learned_at = now(), is_profile_complete = %s, updated_at = now()
            WHERE id = %s
            """,
            (text[:5000], bool(profile["description"]) or len(text) > 200, profile["id"]),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_profile()


def _row_to_dict(row) -> Dict:
    keys = ["id"] + _COLUMNS + ["created_at", "updated_at"]
    d = dict(zip(keys, row))
    for k in ("last_learned_at", "created_at", "updated_at"):
        if d.get(k) and isinstance(d[k], datetime):
            d[k] = d[k].isoformat()
    return d
