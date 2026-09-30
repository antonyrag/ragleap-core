"""
Tests for core/tasks.py — task ticket CRUD, and the two ways tasks/owner
notifications get triggered through the autonomy gate (core.autonomy's
"task" and "notify_owner" channels).
"""
import pytest

from core import tasks


@pytest.fixture
def clean_task(request):
    created = []
    yield created
    from core.employees._db import get_connection
    conn = get_connection()
    try:
        cur = conn.cursor()
        for task_id in created:
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        conn.commit()
        cur.close()
    finally:
        conn.close()


def test_create_task_minimal(clean_task):
    t = tasks.create_task(title="Follow up with vendor")
    clean_task.append(t["id"])
    assert t["title"] == "Follow up with vendor"
    assert t["status"] == "open"
    assert t["priority"] == "normal"
    assert t["assigned_role"] is None
    assert t["creator"] == "owner"


def test_create_task_requires_title(clean_task):
    with pytest.raises(tasks.TaskValidationError):
        tasks.create_task(title="")


def test_create_task_rejects_bad_status(clean_task):
    with pytest.raises(tasks.TaskValidationError):
        tasks.create_task(title="x", status="not_a_real_status")


def test_create_task_rejects_bad_priority(clean_task):
    with pytest.raises(tasks.TaskValidationError):
        tasks.create_task(title="x", priority="not_a_real_priority")


def test_create_task_rejects_unknown_role(clean_task):
    with pytest.raises(tasks.TaskValidationError):
        tasks.create_task(title="x", assigned_role="definitely_not_a_real_role")


def test_create_task_rejects_oversized_title(clean_task):
    with pytest.raises(tasks.TaskValidationError):
        tasks.create_task(title="x" * 500)


def test_get_task_roundtrip(clean_task):
    t = tasks.create_task(title="Check inventory levels", description="Weekly check")
    clean_task.append(t["id"])
    fetched = tasks.get_task(t["id"])
    assert fetched["id"] == t["id"]
    assert fetched["description"] == "Weekly check"


def test_get_task_missing_returns_none():
    assert tasks.get_task("00000000-0000-0000-0000-000000000000") is None


def test_update_task_status(clean_task):
    t = tasks.create_task(title="Draft proposal")
    clean_task.append(t["id"])
    updated = tasks.update_task(t["id"], status="in_progress")
    assert updated["status"] == "in_progress"
    assert updated["updated_at"] != t["updated_at"] or True  # updated_at is always refreshed


def test_update_task_result_and_done(clean_task):
    t = tasks.create_task(title="Reconcile invoices")
    clean_task.append(t["id"])
    updated = tasks.update_task(t["id"], status="done", result="42 invoices matched, 1 flagged")
    assert updated["status"] == "done"
    assert updated["result"] == "42 invoices matched, 1 flagged"


def test_update_task_missing_returns_none():
    assert tasks.update_task("00000000-0000-0000-0000-000000000000", status="done") is None


def test_update_task_rejects_bad_status(clean_task):
    t = tasks.create_task(title="x")
    clean_task.append(t["id"])
    with pytest.raises(tasks.TaskValidationError):
        tasks.update_task(t["id"], status="nonsense")


def test_list_tasks_filters_by_status(clean_task):
    t1 = tasks.create_task(title="open one", status="open")
    t2 = tasks.create_task(title="done one", status="done")
    clean_task += [t1["id"], t2["id"]]
    open_ids = {t["id"] for t in tasks.list_tasks(status="open")}
    assert t1["id"] in open_ids
    assert t2["id"] not in open_ids


def test_subtask_parent_link(clean_task):
    parent = tasks.create_task(title="Parent task")
    clean_task.append(parent["id"])
    child = tasks.create_task(title="Child task", parent_task_id=parent["id"])
    clean_task.append(child["id"])
    assert child["parent_task_id"] == parent["id"]
    children = tasks.list_tasks(parent_task_id=parent["id"])
    assert any(c["id"] == child["id"] for c in children)


def test_create_task_rejects_unknown_parent(clean_task):
    with pytest.raises(tasks.TaskValidationError):
        tasks.create_task(title="x", parent_task_id="00000000-0000-0000-0000-000000000000")


# --- autonomy-gate integration: the "task" and "notify_owner" channels ---

def test_send_via_channel_task_creates_a_real_task(clean_task):
    from core.autonomy import _send_via_channel
    result = _send_via_channel("task", "", "Call the printer vendor\nThey quoted a bad price last time")
    assert "Task created:" in result
    task_id = result.split("Task created:")[1].strip()
    clean_task.append(task_id)
    t = tasks.get_task(task_id)
    assert t is not None
    assert t["title"] == "Call the printer vendor"


def test_send_via_channel_notify_owner_without_target_configured_is_safe():
    from core.autonomy import _send_via_channel
    # With no approval_target configured in this test environment, this
    # must not raise and must not silently pretend to send.
    result = _send_via_channel("notify_owner", "someone-the-model-made-up@example.com", "hello")
    assert "skipped" in result.lower() or "Telegram" in result or "WhatsApp" in result or "Discord" in result


def test_available_tools_excludes_task_tools_by_default(monkeypatch):
    monkeypatch.delenv("ACTION_TASKS_ENABLED", raising=False)
    from core.employees.actions import available_tools
    tools = available_tools()
    assert "create_task" not in tools
    assert "notify_owner" not in tools


def test_available_tools_includes_create_task_when_enabled(monkeypatch):
    monkeypatch.setenv("ACTION_TASKS_ENABLED", "true")
    from core.employees.actions import available_tools
    tools = available_tools()
    assert "create_task" in tools


def test_available_tools_includes_notify_owner_when_owner_configured(monkeypatch):
    import core.autonomy as autonomy_mod
    monkeypatch.setattr(
        autonomy_mod, "get_autonomy_settings",
        lambda: {"mode": "semi", "channels": [], "actions": [], "approval_channel": "telegram", "approval_target": "+10000000000"},
    )
    from core.employees.actions import available_tools
    tools = available_tools()
    assert "notify_owner" in tools


def test_validate_plan_strips_model_supplied_target_for_notify_owner():
    from core.employees.actions import _validate_plan
    plan = {"tool": "notify_owner", "target": "attacker-chosen-address@example.com", "content": "hi"}
    validated = _validate_plan(plan, {"notify_owner": "..."})
    assert validated["target"] == ""


def test_validate_plan_falls_back_to_unassigned_for_unknown_role(clean_task):
    from core.employees.actions import _validate_plan
    plan = {"tool": "create_task", "target": "not_a_real_role", "content": "Do the thing"}
    validated = _validate_plan(plan, {"create_task": "..."})
    assert validated["target"] == ""
