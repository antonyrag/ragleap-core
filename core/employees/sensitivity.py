"""
is_sensitive_role(): the single place that decides whether an AI Employee role is
treated as a sensitive domain (forced semi/off autonomy, reasoning mode and the
grounding check).

- Built-in roles: sensitive exactly when listed in SENSITIVE_DOMAIN_ROLES. Never
  exemptable, never looked up in the database.
- Runtime roles (created via PATCH /employees/{role}, not in DEFAULT_ROLES): sensitive
  when a whole-word marker (legal, medical, tax, ...) appears in the role name, display
  name or skill tags. Owner overrides in .env: SENSITIVE_ROLES_EXTRA forces a role
  sensitive; SENSITIVE_ROLES_REVIEWED_SAFE exempts a runtime role (never a built-in
  sensitive one).
- Only ever tightens. If the check fails unexpectedly it returns True (fail closed).
Never raises. Matching is token based (split on non-alphanumerics), linear time.
"""
import logging
import os
import re

from core.employees.defaults import DEFAULT_ROLES, SENSITIVE_DOMAIN_ROLES

logger = logging.getLogger(__name__)

SENSITIVE_MARKERS = {
    "legal", "lawyer", "attorney", "law", "medical", "medicine", "health", "healthcare",
    "clinical", "doctor", "patient", "pharmacy", "veterinary", "immigration", "visa",
    "tax", "insurance", "compliance", "regulatory",
}


def _env_names(var: str) -> set:
    return {x.strip().lower() for x in os.environ.get(var, "").split(",") if x.strip()}


def _tokens(text) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if t}


def _builtin_names() -> set:
    return {r["role"] for r in DEFAULT_ROLES}


def is_sensitive_role(role) -> bool:
    if not role:
        return False
    try:
        name = str(role).strip()
        key = name.lower()
        if name in SENSITIVE_DOMAIN_ROLES:
            return True
        if key in _env_names("SENSITIVE_ROLES_EXTRA"):
            return True
        if name in _builtin_names():
            return False
        if key in _env_names("SENSITIVE_ROLES_REVIEWED_SAFE"):
            return False
        tokens = _tokens(name)
        try:
            from core.employees import roles as employee_roles  # lazy: avoids an import cycle
            row = employee_roles.get_role(name)
        except Exception as e:
            logger.warning(f"Sensitivity check could not read role '{name}' (using name only): {e}")
            row = None
        if row:
            tokens |= _tokens(row.get("display_name"))
            for tag in row.get("skill_tags") or []:
                tokens |= _tokens(tag)
        return bool(tokens & SENSITIVE_MARKERS)
    except Exception as e:
        logger.error(f"Sensitivity check failed, treating role as sensitive: {e}")
        return True
