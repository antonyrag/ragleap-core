"""
Test-suite safety guard: refuse to run against a non-test database.

Several tests create/delete rows and rewrite autonomy settings, so running
the suite against a live database pollutes it (this happened: a test's
escalation row and an autonomy_settings update landed in production).
The database name must end in "_test". The check is skipped in CI (the
CI variable GitHub Actions always sets; its databases are throwaway
service containers) or with RAGLEAP_ALLOW_ANY_DB=1.
"""
import os
from typing import Optional

import pytest


def database_guard_error(url: Optional[str], env=None) -> Optional[str]:
    env = os.environ if env is None else env
    if env.get("CI") or env.get("RAGLEAP_ALLOW_ANY_DB") == "1":
        return None
    url = (url or "").strip()
    if not url:
        return None
    name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    if name.endswith("_test"):
        return None
    return (
        f"Refusing to run the test suite against database '{name}': tests create and "
        "delete real rows and rewrite autonomy settings. Point DATABASE_URL at a "
        "database whose name ends in _test (for example ragleap_core_test). "
        "CI and RAGLEAP_ALLOW_ANY_DB=1 skip this check."
    )


def pytest_sessionstart(session):
    msg = database_guard_error(os.environ.get("DATABASE_URL"))
    if msg:
        pytest.exit(msg, returncode=3)
