import sys

import pytest

from ragleap.web import fetch_url_text


def test_import_error_message_includes_the_real_cause(monkeypatch):
    monkeypatch.setitem(sys.modules, "trafilatura", None)
    with pytest.raises(ImportError, match="importing trafilatura failed") as exc:
        fetch_url_text("http://example.invalid/")
    assert "ragleap-rag[web]" in str(exc.value)
    assert exc.value.__cause__ is not None
