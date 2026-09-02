"""Tests for the expanded DEFAULT_ROLES catalog (27 new global professional roles across two batches)."""
import pytest
from core.employees.defaults import (
    ROLE_CHOICES, ROLE_SKILL_TAGS, DEFAULT_ROLES, SENSITIVE_DOMAIN_ROLES,
)

NEW_ROLES = [
    "recruiter", "real_estate_agent", "hospitality_agent", "collections_agent",
    "procurement_agent", "inventory_agent", "logistics_agent", "it_helpdesk",
    "compliance_officer", "content_writer", "social_media_manager", "data_analyst",
    "legal_intake", "healthcare_intake", "event_planner", "travel_agent",
    "insurance_agent",
    "fitness_studio_agent", "tutoring_agent", "auto_service_agent",
    "veterinary_intake", "tax_preparation_intake", "immigration_intake",
    "volunteer_coordinator", "membership_agent", "admissions_agent",
    "vehicle_sales_agent",
]

SENSITIVE_EXPECTED = {
    "legal_intake", "healthcare_intake", "insurance_agent", "compliance_officer",
    "veterinary_intake", "tax_preparation_intake", "immigration_intake",
}


def _role_map():
    return {r["role"]: r for r in DEFAULT_ROLES}


def test_no_duplicate_roles_in_default_roles():
    roles = [r["role"] for r in DEFAULT_ROLES]
    assert len(roles) == len(set(roles)), "duplicate role keys found in DEFAULT_ROLES"


@pytest.mark.parametrize("role", NEW_ROLES)
def test_new_role_registered_in_role_choices(role):
    assert role in ROLE_CHOICES


@pytest.mark.parametrize("role", NEW_ROLES)
def test_new_role_has_skill_tags(role):
    assert role in ROLE_SKILL_TAGS
    assert len(ROLE_SKILL_TAGS[role]) > 0


@pytest.mark.parametrize("role", NEW_ROLES)
def test_new_role_has_complete_default_entry(role):
    rm = _role_map()
    assert role in rm, f"{role} missing from DEFAULT_ROLES"
    entry = rm[role]
    for key in ("role", "display_name", "channels", "skill_tags", "personality"):
        assert entry.get(key), f"{role} missing/empty '{key}'"
    assert isinstance(entry["channels"], list) and len(entry["channels"]) > 0
    assert len(entry["personality"]) >= 50, f"{role} personality too short to be a real prompt"


def test_sensitive_domain_roles_are_a_subset_of_role_choices():
    assert SENSITIVE_DOMAIN_ROLES.issubset(set(ROLE_CHOICES))


def test_sensitive_domain_roles_include_all_expected():
    assert SENSITIVE_EXPECTED.issubset(SENSITIVE_DOMAIN_ROLES)


def test_existing_nine_roles_untouched():
    rm = _role_map()
    original = ["manager", "secretary", "ceo", "sales", "support",
                "hr", "finance", "marketing", "operations"]
    for role in original:
        assert role in rm, f"existing role {role} was removed"


def test_no_role_in_default_roles_is_missing_from_role_choices():
    for r in DEFAULT_ROLES:
        assert r["role"] in ROLE_CHOICES, f"{r['role']} in DEFAULT_ROLES but not ROLE_CHOICES"


def test_total_role_count_at_least_36():
    assert len(DEFAULT_ROLES) >= 36
