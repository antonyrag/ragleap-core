import io
import zipfile

import pytest

from ragleap import parsers


def _zip(members):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return b.getvalue()


def test_zip_within_limits_still_extracts():
    out = parsers.extract_text("a.zip", _zip({"a.txt": "alpha", "b.txt": "beta"}))
    assert "alpha" in out and "beta" in out


def test_too_many_members_is_rejected(monkeypatch):
    monkeypatch.setattr(parsers, "MAX_ZIP_MEMBERS", 3)
    with pytest.raises(ValueError, match="members"):
        parsers.extract_text("a.zip", _zip({f"{i}.txt": "x" for i in range(5)}))


def test_declared_size_over_limit_is_rejected(monkeypatch):
    monkeypatch.setattr(parsers, "MAX_ZIP_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(ValueError, match="uncompressed"):
        parsers.extract_text("a.zip", _zip({"big.txt": "a" * 1000}))


def test_container_formats_are_checked_too(monkeypatch):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("hello")
    b = io.BytesIO()
    d.save(b)
    monkeypatch.setattr(parsers, "MAX_ZIP_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(ValueError, match="uncompressed"):
        parsers.extract_text("a.docx", b.getvalue())


def test_running_budget_applies_even_if_the_precheck_is_bypassed(monkeypatch):
    monkeypatch.setattr(parsers, "_check_zip_limits", lambda raw_bytes: None)
    monkeypatch.setattr(parsers, "MAX_ZIP_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(ValueError, match="uncompressed"):
        parsers.extract_text("a.zip", _zip({"big.txt": "a" * 1000}))
