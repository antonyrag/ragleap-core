"""AI Employee role CRUD — single-tenant port of production's AIEmployeeRole model."""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from core.employees._db import get_connection
from core.employees.defaults import DEFAULT_ROLES

logger = logging.getLogger(__name__)


def seed_default_roles() -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM employee_roles")
        if cur.fetchone()[0] > 0:
            cur.close()
            return 0
        for r in DEFAULT_ROLES:
            cur.execute(
                """
                INSERT INTO employee_roles (role, display_name, channels, skill_tags, personality)
                VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (role) DO NOTHING
                """,
                (r["role"], r["display_name"], json.dumps(r["channels"]),
                 json.dumps(r["skill_tags"]), r["personality"]),
            )
        conn.commit()
        cur.close()
        return len(DEFAULT_ROLES)
    finally:
        conn.close()


def get_role(role: str) -> Optional[Dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, role, display_name, is_active, channels, skill_tags,
                   personality, skills_summary, last_learned_at, created_at, updated_at
            FROM employee_roles WHERE role = %s
            """,
            (role,),
        )
        row = cur.fetchone()
        cur.close()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_roles(active_only: bool = False) -> List[Dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        sql = """
            SELECT id, role, display_name, is_active, channels, skill_tags,
                   personality, skills_summary, last_learned_at, created_at, updated_at
            FROM employee_roles
        """
        if active_only:
            sql += " WHERE is_active = true"
        sql += " ORDER BY created_at"
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def upsert_role(role, display_name=None, channels=None, skill_tags=None,
                 personality=None, is_active=None) -> Dict:
    existing = get_role(role)
    conn = get_connection()
    try:
        cur = conn.cursor()
        if existing is None:
            cur.execute(
                """
                INSERT INTO employee_roles (role, display_name, channels, skill_tags, personality, is_active)
                VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s)
                """,
                (role, display_name or "", json.dumps(channels or []),
                 json.dumps(skill_tags or []), personality or "",
                 is_active if is_active is not None else True),
            )
        else:
            updates, params = [], []
            if display_name is not None:
                updates.append("display_name = %s"); params.append(display_name)
            if channels is not None:
                updates.append("channels = %s::jsonb"); params.append(json.dumps(channels))
            if skill_tags is not None:
                updates.append("skill_tags = %s::jsonb"); params.append(json.dumps(skill_tags))
            if personality is not None:
                updates.append("personality = %s"); params.append(personality)
            if is_active is not None:
                updates.append("is_active = %s"); params.append(is_active)
            if updates:
                updates.append("updated_at = now()")
                params.append(role)
                cur.execute(f"UPDATE employee_roles SET {', '.join(updates)} WHERE role = %s", params)
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_role(role)


def update_role_learning(role: str, skills_summary: str) -> Optional[Dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE employee_roles SET skills_summary = %s, last_learned_at = now(), updated_at = now() WHERE role = %s",
            (skills_summary[:2000], role),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_role(role)


def _row_to_dict(row) -> Dict:
    keys = ["id", "role", "display_name", "is_active", "channels", "skill_tags",
            "personality", "skills_summary", "last_learned_at", "created_at", "updated_at"]
    d = dict(zip(keys, row))
    d["id"] = str(d["id"])
    for k in ("last_learned_at", "created_at", "updated_at"):
        if d.get(k) and isinstance(d[k], datetime):
            d[k] = d[k].isoformat()
    return d
