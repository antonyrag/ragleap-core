"""Tests for ragleap_tools.ingest - ingest_document() and
make_ingest_tool(). Uses a fake RagLeap stand-in rather than a real
instance, same approach as test_search.py: ingest_text()'s own
correctness is ragleap-rag's job (already tested there); this
module's job is the Tool/ToolResult wiring and the metadata threading
around it, which a fake exercises just as well without a live vector
backend or embedding provider."""
from ragleap_tools.ingest import IngestConfig, ingest_document, make_ingest_tool


class FakeIngestResult:
    def __init__(self, document_id, chunks_stored):
        self.document_id = document_id
        self.chunks_stored = chunks_stored


class FakeRagLeap:
    """Stands in for a real RagLeap instance. ingest_text_calls records
    every call's arguments so tests can assert on what ingest_document
    actually passed through - specifically, that metadata is now
    threaded through correctly (the real bug this file's tests exist
    to catch a regression of)."""

    def __init__(self, document_id="doc-123", chunks_stored=3, raise_error=None):
        self._document_id = document_id
        self._chunks_stored = chunks_stored
        self._raise_error = raise_error
        self.ingest_text_calls = []

    def ingest_text(self, filename, text, metadata=None, **kwargs):
        self.ingest_text_calls.append({"filename": filename, "text": text, "metadata": metadata})
        if self._raise_error is not None:
            raise self._raise_error
        return FakeIngestResult(self._document_id, self._chunks_stored)


def test_ingest_document_passes_filename_as_metadata():
    """The real bug this fix closes: metadata was never threaded
    through at all, silently making every ingested document
    unfilterable by search_documents' filename= parameter."""
    rag = FakeRagLeap()
    config = IngestConfig(rag=rag)

    ingest_document(config, "report.pdf", "some extracted text")

    assert rag.ingest_text_calls == [
        {"filename": "report.pdf", "text": "some extracted text", "metadata": {"filename": "report.pdf"}}
    ]


def test_ingest_document_returns_document_id_and_chunks_stored():
    rag = FakeRagLeap(document_id="doc-456", chunks_stored=7)
    config = IngestConfig(rag=rag)

    result = ingest_document(config, "notes.txt", "text content")

    assert result.success is True
    assert result.result == {"document_id": "doc-456", "chunks_stored": 7}


def test_ingest_document_catches_value_error():
    rag = FakeRagLeap(raise_error=ValueError("No chunks produced from input text"))
    config = IngestConfig(rag=rag)

    result = ingest_document(config, "empty.txt", "")

    assert result.success is False
    assert "No chunks produced" in result.error


def test_make_ingest_tool_returns_bound_tool():
    rag = FakeRagLeap(document_id="doc-789", chunks_stored=2)
    config = IngestConfig(rag=rag)
    tool = make_ingest_tool(config)

    assert tool.name == "ingest_document"
    result = tool.call(filename="doc.txt", text="content")

    assert result.success is True
    assert result.result["document_id"] == "doc-789"
    assert rag.ingest_text_calls[0]["metadata"] == {"filename": "doc.txt"}


def test_make_ingest_tool_has_valid_openai_schema():
    config = IngestConfig(rag=FakeRagLeap())
    tool = make_ingest_tool(config)
    schema = tool.to_openai_schema()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "ingest_document"
    assert set(schema["function"]["parameters"]["required"]) == {"filename", "text"}


def test_make_ingest_tool_has_valid_gemini_schema():
    config = IngestConfig(rag=FakeRagLeap())
    tool = make_ingest_tool(config)
    schema = tool.to_gemini_schema()

    assert schema["name"] == "ingest_document"
    assert "parameters" in schema
