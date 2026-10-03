"""
Tests for the approval inbox: autonomy.list_pending / resolve_pending and the
/autonomy/pending routes. Approve and reject go through process_approval_response,
the same path as a chat "YES/NO <id>" reply. No LLM or network; sending is stubbed.
"""
import pytest

from core import autonomy as au
from core.employees._db import get_connection

_REAL_REQUEST_APPROVAL = au.request_approval


@pytest.fixture
def semi(monkeypatch):
    state = {"sent": [], "ids": [], "target": "+10000000000"}
    monkeypatch.setattr(au, "get_autonomy_settings", lambda: {
        "mode": "semi", "channels": [], "actions": [],
        "approval_channel": "telegram", "approval_target": state["target"]})
    monkeypatch.setattr(au, "_send_via_channel",
                        lambda ch, t, c: (state["sent"].append((ch, t, c)) or "sent-ok"))
    monkeypatch.setattr(au, "request_approval", lambda *a, **k: True)
    monkeypatch.setattr(au, "log_autonomous_action", lambda *a, **k: None)
    monkeypatch.setattr(au.employee_learning, "learn_from_owner_approval", lambda *a, **k: None)
    yield state
    conn = get_connection()
    try:
        cur = conn.cursor()
        for i in state["ids"]:
            cur.execute("DELETE FROM autonomy_pending WHERE action_id = %s", (i,))
        conn.commit()
        cur.close()
    finally:
        conn.close()


def make_pending(state, content="print(1)"):
    res = au.execute_or_request(action_type="run_code", channel="code", target="", content=content)
    assert res["status"] == "pending_approval"
    state["ids"].append(res["action_id"])
    return res["action_id"]


def ids_now():
    return [p["action_id"] for p in au.list_pending(200)]


def test_list_shows_full_content_newest_first(semi):
    a = make_pending(semi, "x" * 5000)
    b = make_pending(semi, "print(2)")
    items = au.list_pending()
    order = [i["action_id"] for i in items]
    assert order.index(b) < order.index(a)
    entry = next(i for i in items if i["action_id"] == a)
    assert len(entry["content"]) == 5000 and isinstance(entry["created_at"], str)
    assert {"action_type", "channel", "target", "subject", "role"} <= set(entry)
    assert len(au.list_pending(limit=1)) == 1


def test_approve_runs_the_action_and_removes_it(semi):
    a = make_pending(semi)
    assert semi["sent"] == []
    reply = au.resolve_pending(a, True)
    assert "approved and executed" in reply
    assert ("code", "", "print(1)") in semi["sent"]
    assert a not in ids_now()
    assert au.resolve_pending(a, True) is None          # already processed


def test_reject_discards_without_running(semi):
    a = make_pending(semi)
    assert "rejected" in au.resolve_pending(a, False)
    assert semi["sent"] == [] and a not in ids_now()


def test_bad_or_unknown_ids_return_none(semi):
    for bad in ("", "short", "../etc/passwd", "ZZZZZZZZZZ", "abc", "ABCDEFGH"):
        assert au.resolve_pending(bad, True) is None
    a = make_pending(semi)
    assert "rejected" in au.resolve_pending(a.lower(), False)     # case-insensitive


def test_pending_still_stored_when_no_approval_target(semi, monkeypatch):
    semi["target"] = ""
    monkeypatch.setattr(au, "request_approval", _REAL_REQUEST_APPROVAL)
    res = au.execute_or_request(action_type="run_code", channel="code", target="", content="print(3)")
    semi["ids"].append(res["action_id"])
    assert res["status"] == "pending_approval" and res["approval_sent"] is False
    assert res["action_id"] in ids_now()


def test_processing_error_text_is_not_leaked(monkeypatch):
    class Boom:
        def cursor(self):
            raise RuntimeError("secret /srv/app path")

        def close(self):
            pass
    monkeypatch.setattr(au, "get_connection", lambda: Boom())
    reply = au.process_approval_response("YES ABCD1234")
    assert reply == "Error processing approval; see server logs." and "secret" not in reply


def test_routes(semi):
    from fastapi import HTTPException
    from core import api
    a = make_pending(semi)
    assert a in [p["action_id"] for p in api.get_pending_actions()["pending"]]
    assert "approved and executed" in api.approve_pending_action(a)["result"]
    b = make_pending(semi)
    assert "rejected" in api.reject_pending_action(b)["result"]
    for call in (lambda: api.approve_pending_action(a), lambda: api.reject_pending_action("ABCDEFGH")):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404
