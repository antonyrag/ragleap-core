"""
Tests for core/proactive_triggers.py -- CRUD/validation, due filtering,
the atomic claim, delivery through the autonomy gate, and failure isolation.
ask() and execute_or_request() are stubbed here, so no LLM call is made.
"""
import uuid

import pytest

from core import proactive_triggers as pt
from core.employees._db import get_connection


@pytest.fixture(autouse=True)
def fake_role(monkeypatch):
    """Only the role 'tester' exists, regardless of what is in the DB."""
    monkeypatch.setattr(pt.employee_roles, "get_role",
                        lambda r: {"role": r} if r == "tester" else None)


@pytest.fixture
def made():
    ids = []
    yield ids
    conn = get_connection()
    try:
        cur = conn.cursor()
        for i in ids:
            cur.execute("DELETE FROM proactive_triggers WHERE id = %s", (i,))
        conn.commit()
        cur.close()
    finally:
        conn.close()


def make(made, **kw):
    args = dict(name="Daily check", role="tester", prompt="Any overdue invoices?", schedule_minutes=60)
    args.update(kw)
    t = pt.create_trigger(**args)
    made.append(t["id"])
    return t


def set_next_run(trigger_id, sql_interval):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE proactive_triggers SET next_run_at = now() + interval '{sql_interval}' WHERE id = %s",
                    (trigger_id,))
        conn.commit()
        cur.close()
    finally:
        conn.close()


# ---- CRUD + validation ----

def test_create_and_get(made):
    t = make(made)
    assert t["name"] == "Daily check" and t["role"] == "tester"
    assert t["schedule_minutes"] == 60 and t["is_active"] is True
    assert t["last_run_at"] is None
    assert pt.get_trigger(t["id"])["id"] == t["id"]
    assert t["id"] in [x["id"] for x in pt.list_triggers()]


@pytest.mark.parametrize("bad", [4, 0, -5, 525601, True, "60", 1.5])
def test_rejects_bad_schedule(made, bad):
    with pytest.raises(pt.TriggerValidationError):
        make(made, schedule_minutes=bad)


def test_rejects_unknown_role_and_missing_fields(made):
    with pytest.raises(pt.TriggerValidationError):
        make(made, role="nobody")
    with pytest.raises(pt.TriggerValidationError):
        make(made, name="  ")
    with pytest.raises(pt.TriggerValidationError):
        make(made, prompt="")
    with pytest.raises(pt.TriggerValidationError):
        make(made, prompt="x" * (pt.MAX_PROMPT_LEN + 1))


def test_update_and_validation(made):
    t = make(made)
    u = pt.update_trigger(t["id"], name="Renamed", schedule_minutes=30, is_active=False)
    assert u["name"] == "Renamed" and u["schedule_minutes"] == 30 and u["is_active"] is False
    with pytest.raises(pt.TriggerValidationError):
        pt.update_trigger(t["id"], schedule_minutes=2)
    with pytest.raises(pt.TriggerValidationError):
        pt.update_trigger(t["id"], name="  ")
    assert pt.update_trigger(str(uuid.uuid4()), name="x") is None


def test_delete(made):
    t = make(made)
    assert pt.delete_trigger(t["id"]) is True
    assert pt.get_trigger(t["id"]) is None
    assert pt.delete_trigger(t["id"]) is False


# ---- due filtering + atomic claim ----

def test_due_filtering(made):
    due = make(made, name="due")
    future = make(made, name="future")
    off = make(made, name="inactive", is_active=False)
    set_next_run(future["id"], "1 hour")
    ids = [x["id"] for x in pt.due_triggers()]
    assert due["id"] in ids
    assert future["id"] not in ids
    assert off["id"] not in ids


def test_claim_is_atomic_and_advances_schedule(made):
    t = make(made, schedule_minutes=60)
    assert pt._claim(t) is True
    assert pt._claim(t) is False          # second worker loses
    after = pt.get_trigger(t["id"])
    assert after["last_run_at"] is not None
    assert t["id"] not in [x["id"] for x in pt.due_triggers()]


# ---- run_trigger ----

def _stub(monkeypatch, answer="All clear.", gate_result=None, ask_raises=None):
    calls = {"ask": [], "gate": []}

    def fake_ask(query, role=None, **kw):
        calls["ask"].append((query, role))
        if ask_raises:
            raise ask_raises
        return {"answer": answer}

    def fake_gate(**kw):
        calls["gate"].append(kw)
        return gate_result or {"status": "executed"}

    import core.chat, core.autonomy
    monkeypatch.setattr(core.chat, "ask", fake_ask)
    monkeypatch.setattr(core.autonomy, "execute_or_request", fake_gate)
    return calls


def test_run_trigger_delivers_through_gate(made, monkeypatch):
    calls = _stub(monkeypatch)
    t = make(made, name="Invoices")
    res = pt.run_trigger(t)
    assert res["status"] == "executed"
    assert calls["ask"] == [("Any overdue invoices?", "tester")]
    g = calls["gate"][0]
    assert g["action_type"] == "proactive_update" and g["channel"] == "notify_owner"
    assert g["target"] == "" and g["role"] == "tester"
    assert g["content"] == "[Invoices] All clear."


def test_run_trigger_passes_through_pending_approval(made, monkeypatch):
    _stub(monkeypatch, gate_result={"status": "pending_approval"})
    assert pt.run_trigger(make(made))["status"] == "pending_approval"


def test_run_trigger_empty_answer_not_delivered(made, monkeypatch):
    calls = _stub(monkeypatch, answer="   ")
    assert pt.run_trigger(make(made))["status"] == "skipped"
    assert calls["gate"] == []


def test_run_trigger_skips_if_already_claimed(made, monkeypatch):
    calls = _stub(monkeypatch)
    t = make(made)
    pt._claim(t)
    assert pt.run_trigger(t)["status"] == "skipped"
    assert calls["ask"] == []


def test_broken_trigger_does_not_raise_or_refire(made, monkeypatch):
    _stub(monkeypatch, ask_raises=RuntimeError("model down"))
    t = make(made)
    res = pt.run_trigger(t)                # must not raise
    assert res["status"] == "error"
    assert t["id"] not in [x["id"] for x in pt.due_triggers()]


def test_run_due_triggers_runs_mine_and_never_raises(made, monkeypatch):
    a, b = make(made, name="a"), make(made, name="b")
    seen = []
    monkeypatch.setattr(pt, "run_trigger", lambda t: seen.append(t["id"]))
    pt.run_due_triggers()
    assert a["id"] in seen and b["id"] in seen

    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(pt, "due_triggers", boom)
    assert pt.run_due_triggers() == 0       # swallowed, not raised


# ---- real autonomy gate: full mode, semi mode (+ approval reply), forcing, off ----

@pytest.fixture
def gate(monkeypatch):
    """Real execute_or_request / process_approval_response; only the actual
    sending, logging and learning are stubbed. Returns a controller."""
    import core.autonomy as au
    import core.chat
    state = {"mode": "full", "sent": [], "pending_ids": [], "sensitive": False}

    monkeypatch.setattr(au, "get_autonomy_settings", lambda: {
        "mode": state["mode"], "channels": [], "actions": [],
        "approval_channel": "telegram", "approval_target": "+10000000000"})
    monkeypatch.setattr(au, "_send_via_channel",
                        lambda channel, target, content: (state["sent"].append((channel, target, content)) or "sent"))
    monkeypatch.setattr(au, "log_autonomous_action", lambda *a, **k: None)
    monkeypatch.setattr(au, "request_approval", lambda *a, **k: True)
    monkeypatch.setattr(au.employee_learning, "learn_from_owner_approval", lambda *a, **k: None)
    import core.employees.sensitivity as sens
    monkeypatch.setattr(sens, "is_sensitive_role", lambda r: state["sensitive"])
    monkeypatch.setattr(core.chat, "ask", lambda query, role=None, **kw: {"answer": "Two invoices overdue."})

    yield state

    conn = get_connection()
    try:
        cur = conn.cursor()
        for a in state["pending_ids"]:
            cur.execute("DELETE FROM autonomy_pending WHERE action_id = %s", (a,))
        conn.commit()
        cur.close()
    finally:
        conn.close()


def test_full_mode_sends_to_owner_immediately(made, gate):
    t = make(made, name="Invoices")
    res = pt.run_trigger(t)
    assert res["status"] == "executed"
    assert gate["sent"] == [("notify_owner", "", "[Invoices] Two invoices overdue.")]


def test_semi_mode_pends_then_owner_yes_dispatches_same_channel(made, gate):
    import core.autonomy as au
    gate["mode"] = "semi"
    t = make(made, name="Invoices")
    res = pt.run_trigger(t)
    assert res["status"] == "pending_approval"
    action_id = res["action_id"]
    gate["pending_ids"].append(action_id)
    assert gate["sent"] == []                      # nothing sent before approval

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT channel, target, content FROM autonomy_pending WHERE action_id = %s", (action_id,))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert row == ("notify_owner", "", "[Invoices] Two invoices overdue.")

    reply = au.process_approval_response(f"YES {action_id}")
    assert "approved and executed" in reply
    assert gate["sent"] == [("notify_owner", "", "[Invoices] Two invoices overdue.")]


def test_semi_mode_owner_no_sends_nothing(made, gate):
    import core.autonomy as au
    gate["mode"] = "semi"
    res = pt.run_trigger(make(made))
    gate["pending_ids"].append(res["action_id"])
    assert "rejected" in au.process_approval_response(f"NO {res['action_id']}")
    assert gate["sent"] == []


def test_sensitive_role_forced_from_full_to_semi(made, gate):
    gate["sensitive"] = True
    res = pt.run_trigger(make(made))
    if res.get("action_id"):
        gate["pending_ids"].append(res["action_id"])
    assert res["status"] == "pending_approval"
    assert gate["sent"] == []


def test_off_mode_is_inert(made, gate):
    gate["mode"] = "off"
    res = pt.run_trigger(make(made))
    assert res["status"] == "skipped"
    assert gate["sent"] == []


# ---- scheduler job ----

async def test_scheduler_job_never_raises(monkeypatch):
    import core.api as api
    called = []
    monkeypatch.setattr(api.core_triggers, "run_due_triggers", lambda: called.append(1))
    await api._run_due_triggers_job()
    assert called == [1]

    def boom():
        raise RuntimeError("kaboom")
    monkeypatch.setattr(api.core_triggers, "run_due_triggers", boom)
    await api._run_due_triggers_job()              # must not raise


# ---- REST routes (called directly, like tests/test_chat_feedback.py) ----

def test_routes_crud_roundtrip(made):
    from core import api
    created = api.create_proactive_trigger(api.TriggerCreateRequest(
        name="Route test", role="tester", prompt="ping", schedule_minutes=15))
    made.append(created["id"])
    tid = created["id"]
    assert api.get_proactive_trigger(tid)["name"] == "Route test"
    assert tid in [x["id"] for x in api.list_proactive_triggers()["triggers"]]
    assert api.list_proactive_triggers(active_only=True)["triggers"]
    upd = api.update_proactive_trigger(tid, api.TriggerUpdateRequest(is_active=False))
    assert upd["is_active"] is False
    assert api.delete_proactive_trigger(tid) == {"deleted": True}


def test_routes_error_codes(made):
    from fastapi import HTTPException
    from core import api
    with pytest.raises(HTTPException) as e:
        api.create_proactive_trigger(api.TriggerCreateRequest(
            name="x", role="tester", prompt="p", schedule_minutes=1))
    assert e.value.status_code == 400
    missing = str(uuid.uuid4())
    for call in (lambda: api.get_proactive_trigger(missing),
                 lambda: api.update_proactive_trigger(missing, api.TriggerUpdateRequest(name="n")),
                 lambda: api.delete_proactive_trigger(missing)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404
