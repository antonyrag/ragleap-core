"""
The approval request message: by default it asks for a chat reply (YES/NO <id>); with
APPROVAL_REPLIES=off (an install whose app cannot receive chat replies) it points to the
approval inbox instead. No network: sending is stubbed.
"""
import pytest

import core.autonomy as au


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(au, "get_autonomy_settings", lambda: {
        "mode": "semi", "channels": [], "actions": [],
        "approval_channel": "telegram", "approval_target": "123"})
    monkeypatch.setattr(au, "_send_via_channel",
                        lambda ch, t, c: (out.append((ch, t, c)) or "Telegram to 123: sent"))
    return out


def test_default_message_asks_for_chat_replies(sent, monkeypatch):
    monkeypatch.delenv("APPROVAL_REPLIES", raising=False)
    assert au.request_approval("run_code", "code", "", "print(1)", "AB12CD34", role="ops") is True
    msg = sent[0][2]
    assert 'Reply "YES AB12CD34" to approve' in msg and 'Reply "NO AB12CD34" to reject' in msg
    assert "/autonomy/pending" not in msg
    assert "Role: ops" in msg and "print(1)" in msg


@pytest.mark.parametrize("value", ["off", "OFF", " off "])
def test_replies_off_points_to_the_inbox(sent, monkeypatch, value):
    monkeypatch.setenv("APPROVAL_REPLIES", value)
    assert au.request_approval("run_code", "code", "", "print(1)", "AB12CD34") is True
    msg = sent[0][2]
    assert "POST /autonomy/pending/AB12CD34/approve" in msg
    assert "POST /autonomy/pending/AB12CD34/reject" in msg
    assert 'Reply "YES' not in msg and 'Reply "NO' not in msg
    assert "print(1)" in msg                       # the owner still sees what is being approved


@pytest.mark.parametrize("value", ["on", "true", "1", ""])
def test_other_values_keep_chat_replies(sent, monkeypatch, value):
    monkeypatch.setenv("APPROVAL_REPLIES", value)
    au.request_approval("run_code", "code", "", "print(1)", "AB12CD34")
    assert 'Reply "YES AB12CD34" to approve' in sent[0][2]
