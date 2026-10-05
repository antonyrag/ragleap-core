"""
AI Office org chart: department definitions, grouping rules, per-role fields and the /org route.
Runs against the test database; role lookups are faked.
"""
import pytest

from core import office, tasks
from core.employees.defaults import DEFAULT_ROLES, SENSITIVE_DOMAIN_ROLES
from core.employees._db import get_connection


def sql(stmt, params=None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(stmt, params or None)
        conn.commit()
        cur.close()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def cleanup():
    yield
    sql("DELETE FROM tasks WHERE title LIKE 'TEST-ORG%'")


def test_every_shipped_role_has_exactly_one_department():
    flat = [r for _name, roles in office.DEPARTMENTS for r in roles]
    assert len(flat) == len(set(flat)), "a role is listed twice"
    shipped = {r["role"] for r in DEFAULT_ROLES}
    assert shipped <= set(flat), shipped - set(flat)   # extra mapped roles (e.g. podcast_producer_agent) are fine


def test_regulated_department_is_exactly_the_sensitive_roles():
    d = dict(office.DEPARTMENTS)
    assert set(d[office.REGULATED]) == set(SENSITIVE_DOMAIN_ROLES)
    for name, roles in office.DEPARTMENTS:
        if name != office.REGULATED:
            assert not set(roles) & set(SENSITIVE_DOMAIN_ROLES), name


def test_department_of_rules():
    assert office.department_of("sales", False) == "Sales & marketing"
    assert office.department_of("legal_intake", True) == office.REGULATED
    assert office.department_of("acme_custom", True) == office.REGULATED
    assert office.department_of("acme_custom", False) == office.OTHER


@pytest.fixture
def fake_roles(monkeypatch):
    base = {"channels": [], "skill_tags": [], "skills_summary": "", "last_learned_at": None, "is_active": True}
    roles = [
        {**base, "role": "sales", "display_name": "Sales", "channels": ["telegram"], "skill_tags": ["lead", "deal"],
         "skills_summary": "Sells things"},
        {**base, "role": "legal_intake", "display_name": "Legal intake"},
        {**base, "role": "acme_legal_helper", "display_name": "Acme legal helper"},
        {**base, "role": "zz_custom_role", "display_name": "Custom", "is_active": False},
    ]
    monkeypatch.setattr(office.employee_roles, "list_roles", lambda active_only=False: roles)
    monkeypatch.setattr(tasks.employee_roles, "get_role", lambda r: {"role": r})


def test_org_chart_grouping_fields_and_open_task_counts(fake_roles):
    for title, status in (("TEST-ORG one", "open"), ("TEST-ORG two", "blocked"), ("TEST-ORG three", "done")):
        tasks.create_task(title=title, assigned_role="sales", status=status)
    org = office.org_chart()
    depts = {d["name"]: d["roles"] for d in org["departments"]}
    assert [r["role"] for r in depts["Sales & marketing"]] == ["sales"]
    assert {r["role"] for r in depts[office.REGULATED]} == {"legal_intake", "acme_legal_helper"}
    assert [r["role"] for r in depts[office.OTHER]] == ["zz_custom_role"]
    sales = depts["Sales & marketing"][0]
    assert sales["open_tasks"] == 2 and sales["channels"] == ["telegram"] and sales["skill_tags"] == ["lead", "deal"]
    assert sales["is_active"] is True and sales["sensitive"] is False and sales["skills_summary"] == "Sells things"
    assert depts[office.OTHER][0]["is_active"] is False
    assert all(r["sensitive"] for r in depts[office.REGULATED])
    assert set(sales) >= {"role", "display_name", "day_used", "month_used", "day_limit", "month_limit",
                          "last_learned_at", "open_tasks"}
    assert org["owner"]["mode"] in ("off", "semi", "full") and org["router"]["note"]
    assert all(d["roles"] for d in org["departments"])          # empty departments are not listed


def test_org_route_needs_the_key(monkeypatch):
    from fastapi.testclient import TestClient
    from core import api
    monkeypatch.setattr(api, "RAGLEAP_API_KEY", "k-test")
    c = TestClient(api.app)
    assert c.get("/org").status_code == 401
    assert c.get("/org", headers={"x-api-key": "wrong"}).status_code == 401
    ok = c.get("/org", headers={"x-api-key": "k-test"})
    assert ok.status_code == 200 and "departments" in ok.json()


def test_page_uses_the_org_and_task_endpoints():
    import pathlib
    js = (pathlib.Path(__file__).resolve().parent.parent / "core" / "office_static" / "app.js").read_text()
    for needle in ('"/org"', '"/tasks"', '"PATCH"', '"POST"', "/employees?active_only=true"):
        assert needle in js, needle
