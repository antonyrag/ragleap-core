"""
Always-run regression tests (no live infrastructure needed) for datetime
handling across every backend.

Background: v0.5.0 shipped OpenSearchBackend using datetime.UTC, which only
exists on Python 3.11+, while this package supports Python 3.10 - so
insert_document() raised AttributeError there. The four older backends also
used the deprecated datetime.utcnow(). These tests fail if either pattern
comes back, on any Python version.
"""
import ast
import pathlib
from unittest.mock import MagicMock

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "ragleap_vectorstores"


def _flagged(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr == "utcnow":
            hits.append((node.lineno, "utcnow() is deprecated on Python 3.12+"))
        if node.attr == "UTC" and isinstance(node.value, ast.Name) and node.value.id == "datetime":
            hits.append((node.lineno, "datetime.UTC only exists on Python 3.11+"))
    return hits


@pytest.mark.parametrize("path", sorted(SRC.glob("*.py")), ids=lambda p: p.name)
def test_no_deprecated_or_py311_only_datetime_apis(path):
    assert _flagged(path) == []


def test_opensearch_insert_document_runs_without_a_live_server():
    from ragleap_vectorstores.opensearch_backend import OpenSearchBackend

    b = OpenSearchBackend.__new__(OpenSearchBackend)
    b._client = MagicMock()
    b.documents_index_name = "unit_documents"

    b.insert_document("doc-1", "f.txt", {"a": 1})

    kwargs = b._client.index.call_args.kwargs
    assert kwargs["index"] == "unit_documents"
    assert kwargs["id"] == "doc-1"
    assert kwargs["body"]["filename"] == "f.txt"
    assert kwargs["body"]["uploaded_at"].endswith("+00:00")
