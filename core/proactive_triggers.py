"""
Proactive triggers for RagLeap Core.
A trigger makes an AI Employee run a prompt on a fixed interval; the answer
goes to the owner through the normal approval gate (execute_or_request, via
the notify_owner channel), so off/semi/full modes, allowlists, budgets and
sensitive-role forcing all apply exactly as for any other autonomous action.

Not related to core/employees/triggers.py (reactive escalation phrases).
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

from core.employees._db import get_connection
from core.employees import roles as employee_roles

logger = logging.getLogger(__name__)

MIN_SCHEDULE_MINUTES = 5
MAX_SCHEDULE_MINUTES = 525600  # one year
MAX_NAME_LEN = 200
MAX_PROMPT_LEN = 4000

_COLUMNS = ("id, name, role, prompt, schedule_minutes, is_active, "
            "last_run_at, next_run_at, created_at, updated_at")


class TriggerValidationError(ValueError):
    """Raised for a caller-fixable validation problem."""


def _validate(name=None, role=None, prompt=None, schedule_minutes=None):
    if name is not None and len(name) > MAX_NAME_LEN:
        raise TriggerValidationError(f"name exceeds {MAX_NAME_LEN} characters")
    if prompt is not None and len(prompt) > MAX_PROMPT_LEN:
        raise TriggerValidationError(f"prompt exceeds {MAX_PROMPT_LEN} characters")
    if role is not None and employee_roles.get_role(role) is None:
        raise TriggerValidationError(f"role '{role}' does not exist")
    if schedule_minutes is not None:
        if (not isinstance(schedule_minutes, int) or isinstance(schedule_minutes, bool)
                or not MIN_SCHEDULE_MINUTES <= schedule_minutes <= MAX_SCHEDULE_MINUTES):
            raise TriggerValidationError(
                f"schedule_minutes must be an integer between {MIN_SCHEDULE_MINUTES} and {MAX_SCHEDULE_MINUTES}")


def _row_to_dict(row) -> Dict:
    d = dict(zip(_COLUMNS.split(", "), row))
    d["id"] = str(d["id"])
    for k in ("last_run_at", "next_run_at", "created_at", "updated_at"):
        if d.get(k) and isinstance(d[k], datetime):
            d[k] = d[k].isoformat()
    return d


def list_triggers(active_only: bool = False) -> List[Dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        sql = f"SELECT {_COLUMNS} FROM proactive_triggers"
        if active_only:
            sql += " WHERE is_active"
        cur.execute(sql + " ORDER BY created_at DESC")
        rows = cur.fetchall()
        cur.close()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_trigger(trigger_id: str) -> Optional[Dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNS} FROM proactive_triggers WHERE id = %s", (trigger_id,))
        row = cur.fetchone()
        cur.close()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def create_trigger(name: str, role: str, prompt: str, schedule_minutes: int,
                   is_active: bool = True) -> Dict:
    name = (name or "").strip()
    prompt = (prompt or "").strip()
    if not name:
        raise TriggerValidationError("name is required")
    if not prompt:
        raise TriggerValidationError("prompt is required")
    if not role:
        raise TriggerValidationError("role is required")
    _validate(name=name, role=role, prompt=prompt, schedule_minutes=schedule_minutes)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO proactive_triggers (name, role, prompt, schedule_minutes, is_active)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (name, role, prompt, schedule_minutes, bool(is_active)),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_trigger(str(new_id))


def update_trigger(trigger_id: str, name: Optional[str] = None, role: Optional[str] = None,
                   prompt: Optional[str] = None, schedule_minutes: Optional[int] = None,
                   is_active: Optional[bool] = None) -> Optional[Dict]:
    if name is not None:
        name = name.strip()
        if not name:
            raise TriggerValidationError("name cannot be empty")
    if prompt is not None:
        prompt = prompt.strip()
        if not prompt:
            raise TriggerValidationError("prompt cannot be empty")
    _validate(name=name, role=role, prompt=prompt, schedule_minutes=schedule_minutes)

    updates, params = [], []
    for col, val in (("name", name), ("role", role), ("prompt", prompt),
                     ("schedule_minutes", schedule_minutes), ("is_active", is_active)):
        if val is not None:
            updates.append(f"{col} = %s")
            params.append(val)
    if not updates:
        return get_trigger(trigger_id)
    updates.append("updated_at = now()")
    params.append(trigger_id)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE proactive_triggers SET {', '.join(updates)} WHERE id = %s", params)
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_trigger(trigger_id)


def delete_trigger(trigger_id: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM proactive_triggers WHERE id = %s RETURNING id", (trigger_id,))
        deleted = cur.fetchone() is not None
        conn.commit()
        cur.close()
        return deleted
    finally:
        conn.close()


def due_triggers() -> List[Dict]:
    """Active triggers whose next_run_at has passed."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_COLUMNS} FROM proactive_triggers "
            "WHERE is_active AND next_run_at <= now() ORDER BY next_run_at"
        )
        rows = cur.fetchall()
        cur.close()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _claim(trigger: Dict) -> bool:
    """
    Atomically advance next_run_at. Returns True only for the one caller that
    wins, so two workers can never fire the same trigger, and a trigger that
    fails after being claimed does not refire every minute.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE proactive_triggers
               SET last_run_at = now(),
                   next_run_at = now() + make_interval(mins => schedule_minutes),
                   updated_at = now()
             WHERE id = %s AND is_active AND next_run_at <= now()
            RETURNING id
            """,
            (trigger["id"],),
        )
        won = cur.fetchone() is not None
        conn.commit()
        cur.close()
        return won
    finally:
        conn.close()


def run_trigger(trigger: Dict) -> Dict:
    """
    Run one trigger: ask() the assigned role, deliver the answer through the
    normal approval gate. Never raises.
    """
    from core.chat import ask
    from core.autonomy import execute_or_request
    try:
        if not _claim(trigger):
            return {"status": "skipped", "result": "already claimed or no longer due"}
        result = ask(query=trigger["prompt"], role=trigger["role"])
        answer = ((result or {}).get("answer") or "").strip()
        if not answer:
            return {"status": "skipped", "result": "empty answer"}
        return execute_or_request(
            action_type="proactive_update",
            channel="notify_owner",
            target="",  # ignored by the notify_owner branch on purpose
            content=f"[{trigger['name']}] {answer}",
            role=trigger["role"],
        )
    except Exception as e:
        logger.warning("Proactive trigger '%s' failed (non-fatal): %s", trigger.get("name"), e)
        return {"status": "error", "result": str(e)}


def run_due_triggers() -> int:
    """Called by the scheduler. Runs every due trigger; never raises. Returns how many ran."""
    try:
        due = due_triggers()
    except Exception as e:
        logger.warning("Could not load due proactive triggers (non-fatal): %s", e)
        return 0
    for t in due:
        run_trigger(t)
    return len(due)
