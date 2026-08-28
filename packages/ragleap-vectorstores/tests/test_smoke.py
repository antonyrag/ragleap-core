"""Smoke test - the package imports cleanly and VectorBackend is always
re-exported regardless of which optional backend extras are installed."""
import ragleap_vectorstores


def test_import():
    assert "VectorBackend" in ragleap_vectorstores.__all__
