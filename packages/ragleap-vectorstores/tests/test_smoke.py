"""Smoke test - the package imports cleanly with zero backends registered yet."""
import ragleap_vectorstores


def test_import():
    assert ragleap_vectorstores.__all__ == []
