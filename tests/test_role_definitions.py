"""
Consistency guards for core/employees/defaults.py, so a half-added role (or a new
sensitive-domain role that silently skips the safety rules) fails CI instead of
shipping. Pure data checks: no DB, no network.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.employees import defaults as d

REQUIRED_FIELDS = ("role", "display_name", "channels", "skill_tags", "personality")
KNOWN_CHANNELS = {"email", "telegram", "voice", "web_embed", "whatsapp", "discord"}
# ROLE_SKILL_TAGS also carries context keys that are not roles.
NON_ROLE_TAG_KEYS = {"general", "voice", "whatsapp"}
# Tags marking a domain where a wrong answer can cause real harm. A role with one of
# these must be in SENSITIVE_DOMAIN_ROLES (forced semi/off autonomy, reasoning and
# reflection checks, compliance seeds), or be listed below with a written reason.
SENSITIVE_MARKER_TAGS = {"legal", "compliance", "healthcare", "medical", "clinical", "immigration", "regulatory"}
REVIEWED_NOT_SENSITIVE = {}  # role -> reason it carries a marker tag but is not sensitive


def _unguarded(roles, tag_map, sensitive, reviewed):
    """Roles carrying a sensitive marker tag but neither sensitive nor reviewed."""
    bad = []
    for r in roles:
        name = r["role"]
        tags = set(r.get("skill_tags") or []) | set(tag_map.get(name) or [])
        if tags & SENSITIVE_MARKER_TAGS and name not in sensitive and name not in reviewed:
            bad.append(name)
    return sorted(bad)


def test_role_names_are_unique():
    names = [r["role"] for r in d.DEFAULT_ROLES]
    assert len(names) == len(set(names)), sorted({n for n in names if names.count(n) > 1})


def test_every_default_role_is_fully_defined():
    for r in d.DEFAULT_ROLES:
        for f in REQUIRED_FIELDS:
            assert r.get(f), f"role {r.get('role')!r} is missing '{f}' in DEFAULT_ROLES"
        assert isinstance(r["channels"], list) and isinstance(r["skill_tags"], list), r["role"]
        assert len(r["personality"]) >= 40, f"{r['role']}: personality is too short to be useful"


def test_role_choices_match_default_roles():
    names = {r["role"] for r in d.DEFAULT_ROLES}
    assert set(d.ROLE_CHOICES) == names | {"custom"}, (
        f"ROLE_CHOICES and DEFAULT_ROLES differ. Only in DEFAULT_ROLES: {sorted(names - set(d.ROLE_CHOICES))}; "
        f"only in ROLE_CHOICES: {sorted(set(d.ROLE_CHOICES) - names - {'custom'})}"
    )


def test_role_skill_tags_cover_every_role_and_have_no_unknown_keys():
    names = {r["role"] for r in d.DEFAULT_ROLES}
    assert names <= set(d.ROLE_SKILL_TAGS), f"missing from ROLE_SKILL_TAGS: {sorted(names - set(d.ROLE_SKILL_TAGS))}"
    unknown = set(d.ROLE_SKILL_TAGS) - names - NON_ROLE_TAG_KEYS
    assert not unknown, f"ROLE_SKILL_TAGS has keys that are not roles: {sorted(unknown)}"


def test_channels_are_known():
    for r in d.DEFAULT_ROLES:
        assert set(r["channels"]) <= KNOWN_CHANNELS, (r["role"], sorted(set(r["channels"]) - KNOWN_CHANNELS))


def test_sensitive_roles_are_real_defined_roles():
    names = {r["role"] for r in d.DEFAULT_ROLES}
    assert d.SENSITIVE_DOMAIN_ROLES <= names, sorted(d.SENSITIVE_DOMAIN_ROLES - names)


def test_compliance_seeds_match_sensitive_roles_and_are_well_formed():
    seeds = d.DEFAULT_COMPLIANCE_MEMORY_SEEDS
    assert len(seeds) == len(d.SENSITIVE_DOMAIN_ROLES), (
        "each sensitive-domain role needs one compliance seed in DEFAULT_COMPLIANCE_MEMORY_SEEDS "
        f"({len(d.SENSITIVE_DOMAIN_ROLES)} roles, {len(seeds)} seeds)"
    )
    for s in seeds:
        assert set(s) >= {"tags", "importance", "text"}, s
        assert s["tags"] and s["text"].strip() and 0 < s["importance"] <= 1


def test_sensitive_marker_tags_require_sensitive_domain_role():
    tag_map = d.ROLE_SKILL_TAGS
    bad = _unguarded(d.DEFAULT_ROLES, tag_map, d.SENSITIVE_DOMAIN_ROLES, REVIEWED_NOT_SENSITIVE)
    assert not bad, (
        f"{bad} carry a sensitive-domain tag ({sorted(SENSITIVE_MARKER_TAGS)}) but are not in "
        "SENSITIVE_DOMAIN_ROLES. Add them there (with a compliance seed), or list them in "
        "REVIEWED_NOT_SENSITIVE in this test with a reason."
    )


def test_guard_actually_catches_an_unguarded_role():
    fake = [{"role": "tax_lawyer_bot", "skill_tags": ["legal", "faq"]}, {"role": "faq_bot", "skill_tags": ["faq"]}]
    assert _unguarded(fake, {}, set(), {}) == ["tax_lawyer_bot"]
    assert _unguarded(fake, {}, {"tax_lawyer_bot"}, {}) == []
    assert _unguarded(fake, {}, set(), {"tax_lawyer_bot": "reviewed"}) == []
    assert _unguarded([{"role": "x", "skill_tags": []}], {"x": ["compliance"]}, set(), {}) == ["x"]
