"""
Tests for cron-style proactive trigger schedules: parsing and validation (incl. standard
weekday numbering and timezones), the 5-minute floor, scheduling on create/update, the
atomic claim, a corrupted stored cron, and the API models. Runs against the test database.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from core import proactive_triggers as pt
from core.employees._db import get_connection

UTC = timezone.utc


@pytest.fixture(autouse=True)
def fake_role(monkeypatch):
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
    args = dict(name="Morning brief", role="tester", prompt="Summarise overnight leads")
    args.update(kw)
    t = pt.create_trigger(**args)
    made.append(t["id"])
    return t


def sql(stmt, params=()):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(stmt, params)
        conn.commit()
        cur.close()
    finally:
        conn.close()


def at(t):
    return datetime.fromisoformat(t["next_run_at"])


# ---- pure parsing / timezone ----

def test_next_run_respects_the_timezone():
    after = datetime(2026, 10, 3, 0, 0, tzinfo=UTC)
    assert pt.next_cron_run("0 9 * * *", "Asia/Kolkata", after).astimezone(UTC) == datetime(2026, 10, 3, 3, 30, tzinfo=UTC)
    assert pt.next_cron_run("0 9 * * *", "UTC", after).astimezone(UTC) == datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


def test_weekday_numbers_follow_standard_cron():
    sat = datetime(2026, 10, 3, 6, 0, tzinfo=UTC)               # a Saturday
    assert pt.next_cron_run("30 9 * * 1-5", "UTC", sat).date() == date(2026, 10, 5)       # Monday
    assert pt.next_cron_run("30 9 * * mon-fri", "UTC", sat).date() == date(2026, 10, 5)
    assert pt.next_cron_run("0 9 * * 0", "UTC", sat).date() == date(2026, 10, 4)          # Sunday
    assert pt.next_cron_run("0 9 * * 7", "UTC", sat).date() == date(2026, 10, 4)
    assert pt.next_cron_run("0 9 * * 6", "UTC", sat).date() == date(2026, 10, 3)          # Saturday


def test_weekday_normalisation():
    assert pt._normalise_cron("0 9 * * 1-5") == "0 9 * * mon,tue,wed,thu,fri"
    assert pt._normalise_cron("0 9 * * 0,6") == "0 9 * * sun,sat"
    assert pt._normalise_cron("0 9 * * 7") == "0 9 * * sun"
    assert pt._normalise_cron("0 9 * * mon-fri") == "0 9 * * mon-fri"
    assert pt._normalise_cron("0 9 * * *") == "0 9 * * *"
    for bad in ("0 9 * * */2", "0 9 * * 8", "0 9 * * 5-1", "0 9 * * ?", "0 9 * *", "0 9 * * * *", ""):
        with pytest.raises(pt.TriggerValidationError):
            pt._normalise_cron(bad)


@pytest.mark.parametrize("expr", ["* * * * *", "*/2 * * * *", "0,2 * * * *", "*/4 * * * *", "1-4 * * * *",
                                  "*/7 * * * *"])
def test_too_frequent_is_rejected(expr):
    with pytest.raises(pt.TriggerValidationError, match="more often"):
        pt._check_cron(expr, "UTC")


@pytest.mark.parametrize("expr", ["*/5 * * * *", "0 9 * * mon-fri", "30 18 * * 1-5", "0 */2 * * *",
                                  "15 3 1 * *", "0 9 * * *"])
def test_reasonable_schedules_are_accepted(expr):
    pt._check_cron(expr, "Asia/Kolkata")


@pytest.mark.parametrize("expr, tz", [("61 * * * *", "UTC"), ("a b c d e", "UTC"), ("* * *", "UTC"),
                                      ("0 9 * * *", "Mars/Olympus"), ("0 9 * * *", "not a zone")])
def test_invalid_cron_or_timezone_is_rejected(expr, tz):
    with pytest.raises(pt.TriggerValidationError):
        pt._check_cron(expr, tz)


# ---- create ----

def test_create_cron_trigger_is_scheduled_for_later(made):
    t = make(made, cron="0 9 * * *", timezone="Asia/Kolkata")
    assert t["cron"] == "0 9 * * *" and t["timezone"] == "Asia/Kolkata" and t["schedule_minutes"] is None
    assert at(t) > datetime.now(UTC)
    assert t["id"] not in [x["id"] for x in pt.due_triggers()]


def test_interval_triggers_are_unchanged(made):
    t = make(made, schedule_minutes=60)
    assert t["cron"] is None and t["timezone"] == "UTC" and t["schedule_minutes"] == 60
    assert t["id"] in [x["id"] for x in pt.due_triggers()]       # still due immediately, as before


def test_need_exactly_one_schedule(made):
    with pytest.raises(pt.TriggerValidationError):
        make(made)
    with pytest.raises(pt.TriggerValidationError):
        make(made, schedule_minutes=30, cron="0 9 * * *")
    with pytest.raises(pt.TriggerValidationError):
        make(made, cron="* * * * *")
    with pytest.raises(pt.TriggerValidationError):
        make(made, cron="0 9 * * *", timezone="Mars/Olympus")


def test_database_enforces_one_schedule(made):
    t = make(made, schedule_minutes=60)
    with pytest.raises(Exception):
        sql("UPDATE proactive_triggers SET cron = '0 9 * * *' WHERE id = %s", (t["id"],))


# ---- update ----

def test_switch_interval_to_cron_and_back(made):
    t = make(made, schedule_minutes=60)
    u = pt.update_trigger(t["id"], cron="0 9 * * 1-5", timezone="Asia/Kolkata")
    assert u["cron"] == "0 9 * * 1-5" and u["schedule_minutes"] is None and u["timezone"] == "Asia/Kolkata"
    assert at(u) > datetime.now(UTC)
    b = pt.update_trigger(t["id"], schedule_minutes=30)
    assert b["cron"] is None and b["schedule_minutes"] == 30
    wait = at(b) - datetime.now(UTC)
    assert timedelta(minutes=25) < wait < timedelta(minutes=31)


def test_changing_the_timezone_reschedules(made):
    t = make(made, cron="0 9 * * *", timezone="Asia/Kolkata")
    u = pt.update_trigger(t["id"], timezone="UTC")
    assert u["timezone"] == "UTC" and at(u) != at(t)


def test_update_validation(made):
    t = make(made, cron="0 9 * * *")
    for kw in ({"cron": "* * * * *"}, {"cron": " "}, {"cron": "0 9 * * *", "schedule_minutes": 30},
               {"timezone": "Mars/Olympus"}):
        with pytest.raises(pt.TriggerValidationError):
            pt.update_trigger(t["id"], **kw)
    assert pt.get_trigger(t["id"])["cron"] == "0 9 * * *"
    assert pt.update_trigger(t["id"], name="Renamed")["name"] == "Renamed"


# ---- claim ----

def test_claim_moves_a_cron_trigger_to_its_next_slot(made):
    t = make(made, cron="0 9 * * *", timezone="UTC")
    sql("UPDATE proactive_triggers SET next_run_at = now() - interval '1 minute' WHERE id = %s", (t["id"],))
    t = pt.get_trigger(t["id"])
    assert t["id"] in [x["id"] for x in pt.due_triggers()]
    assert pt._claim(t) is True
    assert pt._claim(t) is False
    after = pt.get_trigger(t["id"])
    nxt = at(after)
    assert nxt > datetime.now(UTC) and nxt.minute == 0 and nxt.hour == 9
    assert after["last_run_at"] is not None


def test_downtime_does_not_cause_a_burst_of_runs(made):
    t = make(made, cron="*/5 * * * *", timezone="UTC")
    sql("UPDATE proactive_triggers SET next_run_at = now() - interval '3 days' WHERE id = %s", (t["id"],))
    t = pt.get_trigger(t["id"])
    assert pt._claim(t) is True
    assert pt._claim(t) is False
    assert at(pt.get_trigger(t["id"])) > datetime.now(UTC)


def test_corrupted_cron_does_not_refire_every_minute(made):
    t = make(made, cron="0 9 * * *")
    sql("UPDATE proactive_triggers SET cron = 'garbage', next_run_at = now() - interval '1 minute' WHERE id = %s",
        (t["id"],))
    t = pt.get_trigger(t["id"])
    assert pt._claim(t) is True
    assert at(pt.get_trigger(t["id"])) - datetime.now(UTC) > timedelta(hours=23)


# ---- API ----

def test_routes_accept_cron(made):
    from fastapi import HTTPException
    from core import api
    t = api.create_proactive_trigger(api.TriggerCreateRequest(
        name="Brief", role="tester", prompt="p", cron="0 9 * * 1-5", timezone="Asia/Kolkata"))
    made.append(t["id"])
    assert t["cron"] == "0 9 * * 1-5" and t["schedule_minutes"] is None
    upd = api.update_proactive_trigger(t["id"], api.TriggerUpdateRequest(cron="30 18 * * *"))
    assert upd["cron"] == "30 18 * * *"
    for bad in (api.TriggerCreateRequest(name="x", role="tester", prompt="p"),
                api.TriggerCreateRequest(name="x", role="tester", prompt="p", cron="* * * * *")):
        with pytest.raises(HTTPException) as e:
            api.create_proactive_trigger(bad)
        assert e.value.status_code == 400


def test_gap_check_samples_distinct_fire_times():
    pt._check_cron("0,10,40 * * * *", "UTC")           # gaps of 10, 30 and 20 minutes: fine
    with pytest.raises(pt.TriggerValidationError, match="more often"):
        pt._check_cron("0,3,30 * * * *", "UTC")        # contains a 3-minute gap
