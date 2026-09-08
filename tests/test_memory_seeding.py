"""
Tests for core/employees/memory.py's seed_default_memory_seeds() -
idempotent seeding of DEFAULT_MEMORY_SEEDS (generic + per-vertical
compliance seeds) into employee_memory. Requires a live DB (same
convention as test_autonomy.py/test_memory_role_scoping.py), reachable
via DATABASE_URL.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.employees.memory import seed_default_memory_seeds, SEED_SOURCE
from core.employees.defaults import DEFAULT_MEMORY_SEEDS, DEFAULT_COMPLIANCE_MEMORY_SEEDS, SENSITIVE_DOMAIN_ROLES
from core.employees._db import get_connection


@pytest.fixture(autouse=True)
def clean_employee_memory():
    """Reset employee_memory before each test so tests do not interfere."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM employee_memory")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    yield


def _seed_row_count():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM employee_memory WHERE source = %s", (SEED_SOURCE,))
        return cur.fetchone()[0]
    finally:
        conn.close()


def test_seeds_all_default_memory_seeds_on_first_run():
    count = seed_default_memory_seeds()
    assert count == len(DEFAULT_MEMORY_SEEDS)
    assert _seed_row_count() == len(DEFAULT_MEMORY_SEEDS)


def test_second_run_is_a_noop():
    first = seed_default_memory_seeds()
    second = seed_default_memory_seeds()
    assert first == len(DEFAULT_MEMORY_SEEDS)
    assert second == 0
    assert _seed_row_count() == len(DEFAULT_MEMORY_SEEDS)  # unchanged, not doubled


def test_compliance_seeds_present_with_correct_tags():
    seed_default_memory_seeds()
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT text_content, tags FROM employee_memory WHERE source = %s",
            (SEED_SOURCE,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    all_text = " ".join(r[0] for r in rows)
    # Every sensitive role should have a compliance seed mentioning it or
    # its domain by name, so this isn't just "seeds got inserted" but
    # "the RIGHT content got inserted".
    assert "HIPAA" in all_text
    assert "attorney-client privilege" in all_text
    assert "coverage determination" in all_text
    assert "unauthorized practice of immigration law" in all_text


def test_healthcare_seed_explicitly_excludes_veterinary():
    """Regression guard for the cross-role tag-bleed risk: healthcare_intake
    and veterinary_intake share the 'healthcare' tag in ROLE_SKILL_TAGS, so
    a role-scoped tag search could surface the HIPAA seed to the vet role
    too. The seed text itself must self-scope to prevent misapplication -
    this test fails if a future edit removes that clarifying sentence."""
    hipaa_seed = next(s for s in DEFAULT_COMPLIANCE_MEMORY_SEEDS if "HIPAA" in s["text"])
    assert "veterinary" in hipaa_seed["text"].lower()
    assert "does not apply" in hipaa_seed["text"].lower()


def test_all_seven_sensitive_roles_have_a_compliance_seed():
    """Every role in SENSITIVE_DOMAIN_ROLES should have at least one
    compliance seed tagged with something in that role's own domain
    vocabulary - a coarse but real check that nobody added a role to
    SENSITIVE_DOMAIN_ROLES without a matching compliance seed."""
    from core.employees.defaults import ROLE_SKILL_TAGS
    for role in SENSITIVE_DOMAIN_ROLES:
        role_tags = set(ROLE_SKILL_TAGS.get(role, []))
        matched = any(
            set(seed["tags"]) & role_tags
            for seed in DEFAULT_COMPLIANCE_MEMORY_SEEDS
        )
        assert matched, f"No compliance seed's tags overlap with {role}'s ROLE_SKILL_TAGS"
