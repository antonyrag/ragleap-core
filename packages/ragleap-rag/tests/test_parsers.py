"""Per-extension extraction tests for ragleap.parsers.extract_text().

Each test builds a minimal real file of that type with the format's own
library and asserts the marker text comes back out. This shows the
parsers work on a minimal sample of each type - not that they handle
complex real-world documents (tables, images, odd encodings).

Needs the 'formats' extra (plus xlwt from the test extra). Locally a
missing library skips the test; in CI (CI=true) it fails, so a dropped
extra cannot silently turn these into skips.
"""
import importlib
import io
import json
import os
import sys
import tempfile
import zipfile
from email.message import EmailMessage

import pytest

from ragleap.parsers import SUPPORTED_EXTENSIONS, extract_text

MARKER = "ragleapmarker"


def _need(module):
    if os.environ.get("CI"):
        return importlib.import_module(module)
    return pytest.importorskip(module)


def _text(s):
    return lambda: s.encode()


def _pdf():
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = f"BT /F1 12 Tf 10 50 Td ({MARKER}) Tj ET".encode()
    objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def _docx():
    docx = _need("docx")
    d = docx.Document()
    d.add_paragraph(MARKER)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def _xlsx():
    openpyxl = _need("openpyxl")
    wb = openpyxl.Workbook()
    wb.active["A1"] = MARKER
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _xls():
    xlwt = _need("xlwt")
    wb = xlwt.Workbook()
    wb.add_sheet("s").write(0, 0, MARKER)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _pptx():
    _need("pptx")
    from pptx import Presentation
    p = Presentation()
    slide = p.slides.add_slide(p.slide_layouts[5])
    slide.shapes.title.text = MARKER
    b = io.BytesIO()
    p.save(b)
    return b.getvalue()


def _odt():
    _need("odf")
    from odf.opendocument import OpenDocumentText
    from odf.text import P
    d = OpenDocumentText()
    d.text.addElement(P(text=MARKER))
    b = io.BytesIO()
    d.write(b)
    return b.getvalue()


def _ods():
    _need("odf")
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P
    d = OpenDocumentSpreadsheet()
    t, r, c = Table(name="s"), TableRow(), TableCell(valuetype="string")
    c.addElement(P(text=MARKER))
    r.addElement(c)
    t.addElement(r)
    d.spreadsheet.addElement(t)
    b = io.BytesIO()
    d.write(b)
    return b.getvalue()


def _odp():
    _need("odf")
    from odf.draw import Frame, Page, TextBox
    from odf.opendocument import OpenDocumentPresentation
    from odf.text import P
    d = OpenDocumentPresentation()
    page = Page(name="p1", masterpagename="Default")
    frame = Frame(width="10cm", height="2cm", x="1cm", y="1cm")
    box = TextBox()
    box.addElement(P(text=MARKER))
    frame.addElement(box)
    page.addElement(frame)
    d.presentation.addElement(page)
    b = io.BytesIO()
    d.write(b)
    return b.getvalue()


def _eml():
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = "s", "a@b.c", "d@e.f"
    m.set_content(MARKER)
    return m.as_bytes()


def _zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("in.txt", MARKER)
    return b.getvalue()


def _epub():
    _need("ebooklib")
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier("x")
    book.set_title("t")
    book.set_language("en")
    chapter = epub.EpubHtml(title="c", file_name="c.xhtml", lang="en")
    chapter.content = f"<html><body><p>{MARKER}</p></body></html>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    path = os.path.join(tempfile.mkdtemp(), "t.epub")
    epub.write_epub(path, book)
    with open(path, "rb") as f:
        return f.read()


def _parquet():
    pa = _need("pyarrow")
    pq = importlib.import_module("pyarrow.parquet")
    b = io.BytesIO()
    pq.write_table(pa.table({"a": [MARKER]}), b)
    return b.getvalue()


GENERATORS = {
    ".txt": _text(f"hello {MARKER}"),
    ".md": _text(f"# t\n{MARKER}"),
    ".sql": _text(f"-- {MARKER}\nSELECT 1;"),
    ".csv": _text(f"a,b\n{MARKER},2\n"),
    ".tsv": _text(f"a\tb\n{MARKER}\t2\n"),
    ".json": lambda: json.dumps({"k": MARKER}).encode(),
    ".xml": _text(f"<r><a>{MARKER}</a></r>"),
    ".xsl": _text(f"<r><a>{MARKER}</a></r>"),
    ".xslt": _text(f"<r><a>{MARKER}</a></r>"),
    ".html": _text(f"<html><body><p>{MARKER}</p></body></html>"),
    ".htm": _text(f"<html><body><p>{MARKER}</p></body></html>"),
    ".rtf": _text("{\\rtf1\\ansi " + MARKER + "}"),
    ".vtt": _text(f"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n{MARKER}\n"),
    ".srt": _text(f"1\n00:00:01,000 --> 00:00:02,000\n{MARKER}\n"),
    ".yaml": _text(f"key: {MARKER}\n"),
    ".yml": _text(f"key: {MARKER}\n"),
    ".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx, ".xls": _xls, ".pptx": _pptx,
    ".odt": _odt, ".ods": _ods, ".odp": _odp, ".eml": _eml, ".zip": _zip,
    ".epub": _epub, ".parquet": _parquet,
}


def _extract(ext, raw):
    try:
        return extract_text("sample" + ext, raw)
    except ValueError as e:
        if "pip install ragleap-rag[formats]" in str(e) and not os.environ.get("CI"):
            pytest.skip(str(e))
        raise


def test_every_supported_extension_has_a_sample():
    assert set(GENERATORS) == set(SUPPORTED_EXTENSIONS)


@pytest.mark.parametrize("ext", sorted(SUPPORTED_EXTENSIONS))
def test_extracts_marker_from_minimal_sample(ext):
    assert MARKER in _extract(ext, GENERATORS[ext]())


@pytest.mark.parametrize("ext", [".doc", ".ppt"])
def test_legacy_office_formats_are_rejected_with_a_conversion_hint(ext):
    with pytest.raises(ValueError, match="legacy binary Office format"):
        extract_text("old" + ext, b"x")


def test_unknown_extension_is_rejected():
    with pytest.raises(ValueError, match="Unsupported file type"):
        extract_text("a.exe", b"x")


def test_parquet_without_pandas_raises_value_error(monkeypatch):
    raw = _parquet()
    monkeypatch.setitem(sys.modules, "pandas", None)
    with pytest.raises(ValueError, match="pandas"):
        extract_text("a.parquet", raw)
