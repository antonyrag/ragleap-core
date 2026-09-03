"""
Autonomous Loop for RagLeap Core.
Single-tenant port of production's api/autonomy_engine.py — no
workspace_id, plain SQL instead of Django ORM, no multi-tenant channel
senders (uses this repo's own channels/*/router.py functions instead).

Modes:
  off  - owner-initiated only (default)
  semi - AI proposes an action, owner approves via a "YES <id>" / "NO <id>"
         reply, action executes only on approval
  full - AI executes directly, logs everything

Two independent allowlist gates - allowed actions, allowed channels - are
checked before mode even matters, so even in "full" mode nothing fires
outside what the owner explicitly permitted. This mirrors production's
safety design exactly; see RFC discussion #171 for the full scoping.

Safety note: "semi" is the strongly recommended default for anything
acting on sensitive data (health, financial, legal contexts) until
there is a real track record - the approval step is the actual safety
mechanism here, not a formality.

Sensitive-role enforcement: if a caller passes a `role` that's listed
in core.employees.defaults.SENSITIVE_DOMAIN_ROLES, execute_or_request()
forces that single call down to "semi" even when the owner's general
mode is "full" -- this is the actual enforcement of the guardrail
documented in defaults.py's SENSITIVE_DOMAIN_ROLES comment, which
previously existed only as a convention nothing in code checked. It
only ever forces full->semi, never semi/off->something looser, and
role is optional throughout (existing callers with no role context
keep working exactly as before).
"""
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from core.employees._db import get_connection

logger = logging.getLogger(__name__)


def get_autonomy_settings() -> Dict:
    """Get current autonomy config. Single-tenant: one row, created on first access."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT mode, channels, actions, approval_channel, approval_target FROM autonomy_settings LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO autonomy_settings (mode, channels, actions, approval_channel, approval_target) "
                "VALUES ('off', '[]', '[]', 'telegram', '') "
                "RETURNING mode, channels, actions, approval_channel, approval_target"
            )
            row = cur.fetchone()
            conn.commit()
        cur.close()
        return {
            "mode": row[0],
            "channels": row[1] if isinstance(row[1], list) else json.loads(row[1] or "[]"),
            "actions": row[2] if isinstance(row[2], list) else json.loads(row[2] or "[]"),
            "approval_channel": row[3],
            "approval_target": row[4],
        }
    except Exception as e:
        logger.error(f"get_autonomy_settings error: {e}")
        return {"mode": "off", "channels": [], "actions": [], "approval_channel": "telegram", "approval_target": ""}
    finally:
        conn.close()


def set_autonomy(mode: str, channels: Optional[List[str]] = None,
                  actions: Optional[List[str]] = None,
                  approval_channel: str = "telegram",
                  approval_target: str = "") -> bool:
    """Update autonomy settings (single-tenant: updates the one row)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM autonomy_settings LIMIT 1")
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE autonomy_settings SET mode=%s, channels=%s, actions=%s, "
                "approval_channel=%s, approval_target=%s, updated_at=now() WHERE id=%s",
                (mode, json.dumps(channels or []), json.dumps(actions or []),
                 approval_channel, approval_target, row[0]),
            )
        else:
            cur.execute(
                "INSERT INTO autonomy_settings (mode, channels, actions, approval_channel, approval_target) "
                "VALUES (%s, %s, %s, %s, %s)",
                (mode, json.dumps(channels or []), json.dumps(actions or []),
                 approval_channel, approval_target),
            )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        logger.error(f"set_autonomy error: {e}")
        return False
    finally:
        conn.close()


def log_autonomous_action(action_type: str, channel: str, target: str,
                           content: str, result: str, approved: bool = True,
                           role: Optional[str] = None) -> None:
    """Log an autonomous action. Table keeps unbounded history; callers
    wanting production's "last 200" behavior should query with LIMIT.
    role is optional and nullable -- older callers/rows keep working."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO autonomy_log (action_type, channel, target, content, result, approved, role) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (action_type, channel, target, content[:2000], result[:2000], approved, role),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"log_autonomous_action error: {e}")
    finally:
        conn.close()


def _send_via_channel(channel: str, target: str, content: str) -> str:
    """
    Dispatch an approved/full-mode action to this repo's own single-tenant
    channel senders. Returns a human-readable result string; never raises.
    """
    try:
        if channel == "whatsapp":
            from channels.whatsapp.router import send_whatsapp_message
            ok = send_whatsapp_message(target, content)
            return f"WhatsApp to {target}: {'sent' if ok else 'failed'}"
        elif channel == "telegram":
            from channels.telegram.router import send_telegram_message
            ok = send_telegram_message(target, content)
            return f"Telegram to {target}: {'sent' if ok else 'failed'}"
        elif channel == "discord":
            from channels.discord.router import send_discord_message
            ok = send_discord_message(target, content)
            return f"Discord to {target}: {'sent' if ok else 'failed'}"
        else:
            return f"Unsupported channel for autonomous send: {channel} (voice has no discrete send - see RFC #171)"
    except Exception as e:
        return f"Send error: {e}"


def request_approval(action_type: str, channel: str, target: str,
                      content: str, action_id: str, role: Optional[str] = None) -> bool:
    """
    Send an approval request to the owner over the configured approval
    channel. Uses the same channel senders as _send_via_channel - approval
    requests themselves are just messages. role is shown to the owner
    when present so they know which AI Employee is asking.
    """
    settings = get_autonomy_settings()
    approval_ch = settings["approval_channel"]
    approval_target = settings["approval_target"]
    if not approval_target:
        logger.warning("No approval_target configured - cannot send approval request")
        return False

    role_line = f"Role: {role}\n" if role else ""
    msg = (
        f"Approval Request\n\n"
        f"Action: {action_type}\n"
        f"{role_line}"
        f"Channel: {channel}\n"
        f"Target: {target}\n\n"
        f"Message preview:\n{content[:300]}\n\n"
        f'Reply "YES {action_id}" to approve\n'
        f'Reply "NO {action_id}" to reject'
    )
    result = _send_via_channel(approval_ch, approval_target, msg)
    return "sent" in result


def execute_or_request(action_type: str, channel: str, target: str,
                        content: str, execute_fn: Optional[Callable] = None,
                        subject: str = "", role: Optional[str] = None) -> Dict:
    """
    Core autonomy dispatcher.
    - off mode: skip
    - allowlist gates (actions, channels) checked before mode matters
    - full mode: execute directly (via execute_fn if given, else the
      default channel sender), log
    - semi mode: store pending, request approval, wait for owner reply

    role (optional): when provided and present in
    core.employees.defaults.SENSITIVE_DOMAIN_ROLES, this single call is
    forced from "full" down to "semi" regardless of the owner's general
    autonomy mode -- the actual enforcement of the guardrail documented
    in defaults.py. Only ever tightens (full->semi), never loosens.

    Returns: {"status": "executed"|"pending_approval"|"skipped"|"error", ...}
    """
    settings = get_autonomy_settings()
    mode = settings["mode"]
    actions = settings["actions"]
    channels = settings["channels"]

    if mode == "off":
        return {"status": "skipped", "result": "autonomy off"}

    if actions and action_type not in actions:
        return {"status": "skipped", "result": f"{action_type} not in allowed actions"}

    if channels and channel not in channels:
        return {"status": "skipped", "result": f"{channel} not in allowed channels"}

    if mode == "full" and role:
        try:
            from core.employees.defaults import SENSITIVE_DOMAIN_ROLES
            if role in SENSITIVE_DOMAIN_ROLES:
                logger.info(
                    f"Sensitive-domain role '{role}' forced full->semi for "
                    f"action_type={action_type} (SENSITIVE_DOMAIN_ROLES guardrail)"
                )
                mode = "semi"
        except Exception as e:
            logger.warning(f"SENSITIVE_DOMAIN_ROLES check failed, proceeding with configured mode: {e}")

    if mode == "full":
        try:
            if execute_fn:
                result = execute_fn()
            else:
                result = _send_via_channel(channel, target, content)
            log_autonomous_action(action_type, channel, target, content, str(result), approved=True, role=role)
            return {"status": "executed", "result": result}
        except Exception as e:
            log_autonomous_action(action_type, channel, target, content, f"ERROR: {e}", approved=True, role=role)
            return {"status": "error", "result": str(e)}

    elif mode == "semi":
        action_id = str(uuid.uuid4())[:8].upper()
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO autonomy_pending (action_id, action_type, channel, target, content, subject, role) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (action_id, action_type, channel, target, content, subject, role),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning(f"failed to store pending action: {e}")
        finally:
            conn.close()

        sent = request_approval(action_type, channel, target, content, action_id, role=role)
        return {"status": "pending_approval", "action_id": action_id, "approval_sent": sent}

    return {"status": "skipped", "result": "unknown mode"}


def process_approval_response(message: str) -> Optional[str]:
    """
    Process an owner reply of the form "YES ABC123" or "NO ABC123".
    Returns a human-readable reply, or None if the message isn't an
    approval response at all (caller should fall through to normal chat).
    """
    msg = message.strip().upper()
    m = re.match(r"^(YES|NO)\s+([A-Z0-9]{8})$", msg)
    if not m:
        return None

    approved = m.group(1) == "YES"
    action_id = m.group(2)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT action_type, channel, target, content, subject, role FROM autonomy_pending WHERE action_id = %s",
            (action_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return f"Action {action_id} not found or already processed."

        action_type, channel, target, content, subject, role = row
        cur.execute("DELETE FROM autonomy_pending WHERE action_id = %s", (action_id,))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"process_approval_response lookup error: {e}", exc_info=True)
        return f"Error processing approval: {e}"
    finally:
        conn.close()

    if not approved:
        log_autonomous_action(action_type, channel, target, content, "REJECTED by owner", approved=False, role=role)
        return f"Action {action_id} rejected and cancelled."

    result = _send_via_channel(channel, target, content)
    log_autonomous_action(action_type, channel, target, content, result, approved=True, role=role)
    return f"Action {action_id} approved and executed.\n{result}"


def generate_autonomy_daily_report() -> str:
    """Generate a report of today's autonomous actions from autonomy_log."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT action_type, result FROM autonomy_log WHERE created_at >= CURRENT_DATE"
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        return f"Report generation error: {e}"
    finally:
        conn.close()

    if not rows:
        return "Autonomy Report - No autonomous actions today."

    by_type: Dict[str, int] = {}
    failed = 0
    for action_type, result in rows:
        by_type[action_type] = by_type.get(action_type, 0) + 1
        if "ERROR" in str(result):
            failed += 1

    lines = [f"Autonomy Report - {datetime.now(timezone.utc).date().isoformat()}", ""]
    lines.append(f"Total actions: {len(rows)}")
    for t, count in by_type.items():
        lines.append(f"  - {t}: {count}")
    if failed:
        lines.append(f"\n{failed} failed actions - check logs")

    return "\n".join(lines)
