"""
n8n workflow automation for RagLeap Core.
Single-tenant port of production's n8n_bridge.py — no workspace_id, plain
SQL instead of Django ORM. Fires a webhook after the AI replies on a
matching channel. Never raises — a broken workflow config should never
break the main chat flow, same guarantee as production.
"""
import json
import logging
from typing import Dict, List, Optional

import requests

from core.employees._db import get_connection

logger = logging.getLogger(__name__)


def call_n8n_workflows(channel: str, message: str, ai_reply: str = "", context: Optional[Dict] = None) -> List[Dict]:
    """
    Finds all active n8n workflows configured for this channel and calls
    each webhook. Returns a list of {"workflow": name, "status": "ok"} for
    successful calls. Silent on failure — logs and continues, never raises.
    """
    results = []
    try:
        workflows = list_workflows(channel=channel, active_only=True)
        for wf in workflows:
            try:
                resp = requests.post(
                    wf["webhook_url"],
                    json={
                        "channel": channel,
                        "message": message,
                        "ai_reply": ai_reply,
                        "context": context or {},
                    },
                    timeout=10,
                )
                if resp.ok:
                    results.append({"workflow": wf["name"], "status": "ok"})
                    logger.info(f"n8n workflow '{wf['name']}' triggered OK for {channel}")
                else:
                    logger.warning(f"n8n workflow '{wf['name']}' returned {resp.status_code}")
            except Exception as e:
                logger.warning(f"n8n workflow '{wf['name']}' failed: {e}")
    except Exception as e:
        logger.error(f"call_n8n_workflows error: {e}")
    return results


def list_workflows(channel: Optional[str] = None, active_only: bool = False) -> List[Dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        sql = "SELECT id, name, description, webhook_url, channels, is_active, created_at, updated_at FROM n8n_workflows"
        clauses = []
        if active_only:
            clauses.append("is_active = true")
        if channel:
            clauses.append("channels ? %s")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at"
        cur.execute(sql, (channel,) if channel else ())
        rows = cur.fetchall()
        cur.close()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_workflow(workflow_id: str) -> Optional[Dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, description, webhook_url, channels, is_active, created_at, updated_at FROM n8n_workflows WHERE id = %s",
            (workflow_id,),
        )
        row = cur.fetchone()
        cur.close()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def create_workflow(name: str, webhook_url: str, description: str = "", channels: Optional[List[str]] = None, is_active: bool = False) -> Dict:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO n8n_workflows (name, description, webhook_url, channels, is_active)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            RETURNING id
            """,
            (name, description, webhook_url, json.dumps(channels or []), is_active),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_workflow(str(new_id))


def update_workflow(workflow_id: str, name: Optional[str] = None, description: Optional[str] = None,
                     webhook_url: Optional[str] = None, channels: Optional[List[str]] = None,
                     is_active: Optional[bool] = None) -> Optional[Dict]:
    updates, params = [], []
    if name is not None:
        updates.append("name = %s"); params.append(name)
    if description is not None:
        updates.append("description = %s"); params.append(description)
    if webhook_url is not None:
        updates.append("webhook_url = %s"); params.append(webhook_url)
    if channels is not None:
        updates.append("channels = %s::jsonb"); params.append(json.dumps(channels))
    if is_active is not None:
        updates.append("is_active = %s"); params.append(is_active)
    if not updates:
        return get_workflow(workflow_id)
    updates.append("updated_at = now()")
    params.append(workflow_id)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE n8n_workflows SET {', '.join(updates)} WHERE id = %s", params)
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return get_workflow(workflow_id)


def delete_workflow(workflow_id: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM n8n_workflows WHERE id = %s", (workflow_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        cur.close()
        return deleted
    finally:
        conn.close()


def _row_to_dict(row) -> Dict:
    from datetime import datetime
    keys = ["id", "name", "description", "webhook_url", "channels", "is_active", "created_at", "updated_at"]
    d = dict(zip(keys, row))
    d["id"] = str(d["id"])
    for k in ("created_at", "updated_at"):
        if d.get(k) and isinstance(d[k], datetime):
            d[k] = d[k].isoformat()
    return d
