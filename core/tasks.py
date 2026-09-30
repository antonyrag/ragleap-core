"""
Task tickets for RagLeap Core.
Single-tenant, plain-SQL, mirrors core/workflows.py's style. AI employees
(via the action planner) and the owner (via the API) can create, assign,
and update tasks.
"""
import logging
from typing import Dict, List, Optional

from core.employees._db import get_connection
from core.employees import roles as employee_roles

logger = logging.getLogger(__name__)

VALID_STATUSES = ("open", "in_progress", "blocked", "done", "cancelled")
VALID_PRIORITIES = ("low", "normal", "high", "urgent")
MAX_TITLE_LEN = 200
MAX_DESCRIPTION_LEN = 4000
MAX_RESULT_LEN = 4000


class TaskValidationError(ValueError):
    """Raised for a caller-fixable validation problem (bad status, unknown role, text too long)."""


def _validate_status(status: str):
    if status not in VALID_STATUSES:
        raise TaskValidationError(f"status must be one of: {', '.join(VALID_STATUSES)}")


def _validate_priority(priority: str):
    if priority not in VALID_PRIORITIES:
        raise TaskValidationError(f"priority must be one of: {', '.join(VALID_PRIORITIES)}")


def _validate_role(role: Optional[str]):
    if role is None or role == "":
        return
    if employee_roles.get_role(role) is None:
        raise TaskValidationError(f"assigned_role '{role}' does not exist")


def _validate_text_lengths(title=None, description=None, result=None):
    if title is not None and len(title) > MAX_TITLE_LEN:
        raise TaskValidationError(f"title exceeds {MAX_TITLE_LEN} characters")
    if description is not None and len(description) > MAX_DESCRIPTION_LEN:
        raise TaskValidationError(f"description exceeds {MAX_DESCRIPTION_LEN} characters")
    if result is not None and len(result) > MAX_RESULT_LEN:
        raise TaskValidationError(f"result exceeds {MAX_RESULT_LEN} characters")


_COLUMNS = "id, title, description, status, priority, assigned_role, creator, parent_task_id, due_date, result, created_at, updated_at"


def list_tasks(status: Optional[str] = None, assigned_role: Optional[str] = None,
               parent_task_id: Optional[str] = None) -> List[Dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        sql = f"SELECT {_COLUMNS} FROM tasks"
        clauses, params = [], []
        if status:
            clauses.append("status = %s"); params.append(status)
        if assigned_role:
            clauses.append("assigned_role = %s"); params.append(assigned_role)
        if parent_task_id:
            clauses.append("parent_task_id = %s"); params.append(parent_task_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_task(task_id: str) -> Optional[Dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNS} FROM tasks WHERE id = %s", (task_id,))
        row = cur.fetchone()
        cur.close()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def create_task(title: str, description: str = "", status: str = "open", priority: str = "normal",
                 assigned_role: Optional[str] = None, creator: str = "owner",
                 parent_task_id: Optional[str] = None, due_date: Optional[str] = None) -> Dict:
    title = (title or "").strip()
    if not title:
        raise TaskValidationError("title is required")
    _validate_text_lengths(title=title, description=description)
    _validate_status(status)
    _validate_priority(priority)
    _validate_role(assigned_role)
    if parent_task_id and get_task(parent_task_id) is None:
        raise TaskValidationError(f"parent_task_id '{parent_task_id}' does not exist")

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO tasks (title, description, status, priority, assigned_role, creator, parent_task_id, due_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (title, description or "", status, priority, assigned_role or None, creator, parent_task_id, due_date),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_task(str(new_id))


def update_task(task_id: str, title: Optional[str] = None, description: Optional[str] = None,
                 status: Optional[str] = None, priority: Optional[str] = None,
                 assigned_role: Optional[str] = None, due_date: Optional[str] = None,
                 result: Optional[str] = None) -> Optional[Dict]:
    if title is not None:
        title = title.strip()
        if not title:
            raise TaskValidationError("title cannot be empty")
    _validate_text_lengths(title=title, description=description, result=result)
    if status is not None:
        _validate_status(status)
    if priority is not None:
        _validate_priority(priority)
    if assigned_role is not None:
        _validate_role(assigned_role)

    updates, params = [], []
    for col, val in (("title", title), ("description", description), ("status", status),
                      ("priority", priority), ("assigned_role", assigned_role),
                      ("due_date", due_date), ("result", result)):
        if val is not None:
            updates.append(f"{col} = %s"); params.append(val)
    if not updates:
        return get_task(task_id)
    updates.append("updated_at = now()")
    params.append(task_id)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = %s", params)
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_task(task_id)


def _row_to_dict(row) -> Dict:
    from datetime import datetime
    keys = _COLUMNS.split(", ")
    d = dict(zip(keys, row))
    d["id"] = str(d["id"])
    if d.get("parent_task_id"):
        d["parent_task_id"] = str(d["parent_task_id"])
    for k in ("created_at", "updated_at", "due_date"):
        if d.get(k) and isinstance(d[k], datetime):
            d[k] = d[k].isoformat()
    return d
