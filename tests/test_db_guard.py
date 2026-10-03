"""Tests for the database guard in tests/conftest.py (pure function, no DB access)."""
import importlib.util
import pathlib

import pytest

_spec = importlib.util.spec_from_file_location(
    "ragleap_db_guard", pathlib.Path(__file__).resolve().parent / "conftest.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

BASE = "postgresql://user:p@ss-word@localhost:5433/"


@pytest.mark.parametrize("name", ["ragleap_core", "ragleap", "postgres", "ragleap_test_data", "prod"])
def test_refuses_non_test_names(name):
    msg = guard.database_guard_error(BASE + name, env={})
    assert msg and f"'{name}'" in msg


@pytest.mark.parametrize("url", [
    BASE + "ragleap_core_test", BASE + "ragleap_test", BASE + "x_test?sslmode=require", BASE + "x_test/"])
def test_allows_test_databases(url):
    assert guard.database_guard_error(url, env={}) is None


def test_ci_and_explicit_override_skip_the_check():
    assert guard.database_guard_error(BASE + "ragleap_core", env={"CI": "true"}) is None
    assert guard.database_guard_error(BASE + "ragleap_core", env={"RAGLEAP_ALLOW_ANY_DB": "1"}) is None
    assert guard.database_guard_error(BASE + "ragleap_core", env={"RAGLEAP_ALLOW_ANY_DB": "0"})


def test_unset_url_is_not_blocked():
    assert guard.database_guard_error(None, env={}) is None
    assert guard.database_guard_error("  ", env={}) is None


def test_message_never_contains_credentials():
    msg = guard.database_guard_error(BASE + "ragleap_core", env={})
    assert "p@ss-word" not in msg and "user" not in msg and "localhost" not in msg


def test_session_start_exits_for_production_name(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", BASE + "ragleap_core")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("RAGLEAP_ALLOW_ANY_DB", raising=False)
    with pytest.raises(pytest.exit.Exception):
        guard.pytest_sessionstart(None)
