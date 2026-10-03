"""
Proactive triggers for RagLeap Core.
A trigger makes an AI Employee run a prompt on a schedule; the answer goes to the owner
through the normal approval gate (execute_or_request, via the notify_owner channel), so
off/semi/full modes, allowlists, budgets and sensitive-role forcing all apply exactly as
for any other autonomous action.

Schedules: EITHER schedule_minutes (every N minutes, minimum 5) OR cron (a standard
5-field crontab expression evaluated in `timezone`, for example "0 9 * * 1-5" in
Asia/Kolkata = 09:00 on weekdays IST), never both. Weekday numbers follow standard cron
(0 or 7 = Sunday, 1 = Monday); names such as mon-fri also work. A cron schedule may not
fire more often than every 5 minutes. After downtime a cron trigger fires at most once and
then resumes its normal schedule.

Not related to core/employees/triggers.py (reactive escalation phrases).
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Dict, List, Optional

from apscheduler.triggers.cron import CronTrigger
from apscheduler.util import astimezone

from core.employees._db import get_connection
from core.employees import roles as employee_roles

logger = logging.getLogger(__name__)

MIN_SCHEDULE_MINUTES = 5
MAX_SCHEDULE_MINUTES = 525600  # one year
MAX_NAME_LEN = 200
MAX_PROMPT_LEN = 4000
MAX_CRON_LEN = 100

_COLUMNS = ("id, name, role, prompt, schedule_minutes, cron, timezone, is_active, "
            "last_run_at, next_run_at, created_at, updated_at")
_DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]


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


# ---------------- cron helpers ----------------

def _tz(tz_name: str):
    try:
        tz = astimezone((tz_name or "UTC").strip() or "UTC")
    except Exception:
        tz = None
    if tz is None:
        raise TriggerValidationError("unknown timezone (use an IANA name such as Asia/Kolkata or UTC)")
    return tz


def _normalise_weekday(field: str) -> str:
    """Standard cron weekday numbers (0/7 = Sunday, 1 = Monday) -> names, which are unambiguous."""
    if field == "*" or any(c.isalpha() for c in field):
        return field
    names = []
    for part in field.split(","):
        if not part or "/" in part:
            raise TriggerValidationError(
                "weekday steps are not supported; list the days instead (for example 1,3,5 or mon,wed,fri)")
        a, b = part.split("-", 1) if "-" in part else (part, part)
        if not (a.isdigit() and b.isdigit()) or not (0 <= int(a) <= 7 and 0 <= int(b) <= 7 and int(a) <= int(b)):
            raise TriggerValidationError("invalid weekday in cron expression")
        for n in range(int(a), int(b) + 1):
            if _DAYS[n % 7] not in names:
                names.append(_DAYS[n % 7])
    return ",".join(names)


def _normalise_cron(expr: str) -> str:
    fields = (expr or "").split()
    if len(fields) != 5 or len(expr) > MAX_CRON_LEN:
        raise TriggerValidationError("cron must have 5 fields: minute hour day-of-month month weekday")
    fields[4] = _normalise_weekday(fields[4])
    return " ".join(fields)


def _cron_trigger(expr: str, tz_name: str) -> CronTrigger:
    normalised = _normalise_cron(expr)
    tz = _tz(tz_name)
    try:
        return CronTrigger.from_crontab(normalised, timezone=tz)
    except Exception:
        raise TriggerValidationError("invalid cron expression")


def _check_cron(expr: str, tz_name: str) -> CronTrigger:
    """Validate an expression: parses, fires, and never more often than every 5 minutes."""
    trig = _cron_trigger(expr, tz_name)
    now = datetime.now(dt_timezone.utc)
    times, cur = [], now
    for _ in range(30):
        nxt = trig.get_next_fire_time(None, cur)
        if nxt is None:
            break
        times.append(nxt)
        cur = nxt + timedelta(seconds=1)   # the library only looks forward from the time it is given
    if not times:
        raise TriggerValidationError("cron expression never fires")
    for a, b in zip(times, times[1:]):
        if b - a < timedelta(minutes=MIN_SCHEDULE_MINUTES):
            raise TriggerValidationError(f"cron fires more often than every {MIN_SCHEDULE_MINUTES} minutes")
    return trig


def next_cron_run(expr: str, tz_name: str, after: Optional[datetime] = None) -> datetime:
    trig = _cron_trigger(expr, tz_name)
    nxt = trig.get_next_fire_time(None, after or datetime.now(dt_timezone.utc))
    if nxt is None:
        raise TriggerValidationError("cron expression never fires")
    return nxt


# ---------------- CRUD ----------------

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


def create_trigger(name: str, role: str, prompt: str, schedule_minutes: Optional[int] = None,
                   is_active: bool = True, cron: Optional[str] = None, timezone: str = "UTC") -> Dict:
    name = (name or "").strip()
    prompt = (prompt or "").strip()
    cron = (cron or "").strip() or None
    if not name:
        raise TriggerValidationError("name is required")
    if not prompt:
        raise TriggerValidationError("prompt is required")
    if not role:
        raise TriggerValidationError("role is required")
    if schedule_minutes is None and not cron:
        raise TriggerValidationError("give schedule_minutes or cron")
    if schedule_minutes is not None and cron:
        raise TriggerValidationError("give either schedule_minutes or cron, not both")
    _validate(name=name, role=role, prompt=prompt, schedule_minutes=schedule_minutes)
    tz_name = (timezone or "UTC").strip() or "UTC"
    next_run = None
    if cron:
        _check_cron(cron, tz_name)
        next_run = next_cron_run(cron, tz_name)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO proactive_triggers (name, role, prompt, schedule_minutes, is_active, cron, timezone, next_run_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()))
            RETURNING id
            """,
            (name, role, prompt, schedule_minutes, bool(is_active), cron, tz_name, next_run),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_trigger(str(new_id))


def update_trigger(trigger_id: str, name: Optional[str] = None, role: Optional[str] = None,
                   prompt: Optional[str] = None, schedule_minutes: Optional[int] = None,
                   is_active: Optional[bool] = None, cron: Optional[str] = None,
                   timezone: Optional[str] = None) -> Optional[Dict]:
    if name is not None:
        name = name.strip()
        if not name:
            raise TriggerValidationError("name cannot be empty")
    if prompt is not None:
        prompt = prompt.strip()
        if not prompt:
            raise TriggerValidationError("prompt cannot be empty")
    if cron is not None:
        cron = cron.strip()
        if not cron:
            raise TriggerValidationError("cron cannot be empty")
        if schedule_minutes is not None:
            raise TriggerValidationError("give either schedule_minutes or cron, not both")
    _validate(name=name, role=role, prompt=prompt, schedule_minutes=schedule_minutes)
    if timezone is not None:
        timezone = timezone.strip() or "UTC"
        _tz(timezone)
    current = get_trigger(trigger_id)
    if current is None:
        return None

    updates, params = [], []
    for col, val in (("name", name), ("role", role), ("prompt", prompt), ("is_active", is_active)):
        if val is not None:
            updates.append(f"{col} = %s")
            params.append(val)

    effective_cron = current.get("cron")
    if cron is not None:
        effective_cron = cron
    if schedule_minutes is not None:
        effective_cron = None
    effective_tz = timezone if timezone is not None else (current.get("timezone") or "UTC")

    if effective_cron:
        if cron is not None or timezone is not None:       # schedule changed: validate and reschedule
            _check_cron(effective_cron, effective_tz)
            updates += ["cron = %s", "timezone = %s", "schedule_minutes = NULL", "next_run_at = %s"]
            params += [effective_cron, effective_tz, next_cron_run(effective_cron, effective_tz)]
    else:
        if schedule_minutes is not None:
            updates.append("schedule_minutes = %s")
            params.append(schedule_minutes)
            if current.get("cron"):                         # cron -> interval
                updates += ["cron = NULL", "next_run_at = now() + make_interval(mins => %s)"]
                params.append(schedule_minutes)
        if timezone is not None:
            updates.append("timezone = %s")
            params.append(timezone)

    if not updates:
        return current
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


# ---------------- running ----------------

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
    Atomically advance next_run_at. Returns True only for the one caller that wins, so two
    workers can never fire the same trigger, and a trigger that fails after being claimed does
    not refire every minute. A cron trigger's next run is computed from NOW, so downtime never
    causes a burst of missed runs.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        if trigger.get("cron"):
            try:
                nxt = next_cron_run(trigger["cron"], trigger.get("timezone") or "UTC")
            except Exception:
                logger.warning("Trigger '%s' has an unusable cron schedule; retrying in 24h", trigger.get("name"))
                nxt = datetime.now(dt_timezone.utc) + timedelta(hours=24)
            cur.execute(
                """
                UPDATE proactive_triggers
                   SET last_run_at = now(), next_run_at = %s, updated_at = now()
                 WHERE id = %s AND is_active AND next_run_at <= now()
                RETURNING id
                """,
                (nxt, trigger["id"]),
            )
        else:
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
    Run one trigger: ask() the assigned role, deliver the answer through the normal approval
    gate. Never raises.
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
