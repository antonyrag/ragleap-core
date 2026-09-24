"""Tests for ragleap_tools.search - search_documents() and
make_search_tool(). Uses a fake RagLeap stand-in rather than a real
instance: retrieve()'s own correctness is ragleap-rag's job (already
tested there); this module's job is the Tool/ToolResult wiring around
it, which a fake exercises just as well without a live vector
backend."""
from ragleap_tools.search import SearchConfig, make_search_tool, search_documents


class FakeRagLeap:
    """Stands in for a real RagLeap instance. retrieve_calls records
    every call's arguments so tests can assert on what search_documents
    actually passed through."""

    def __init__(self, chunks=None, raise_error=None):
        self._chunks = chunks if chunks is not None else []
        self._raise_error = raise_error
        self.retrieve_calls = []

    def retrieve(self, query, top_k=5, hybrid=True, rerank=False, metadata_filter=None):
        self.retrieve_calls.append(
            {"query": query, "top_k": top_k, "hybrid": hybrid, "rerank": rerank, "metadata_filter": metadata_filter}
        )
        if self._raise_error is not None:
            raise self._raise_error
        return self._chunks


def test_search_documents_returns_chunks_unmodified():
    chunks = [{"text": "hello world", "document_name": "doc1.txt", "score": 0.9}]
    rag = FakeRagLeap(chunks=chunks)
    config = SearchConfig(rag=rag)

    result = search_documents(config, "hello")

    assert result.success is True
    assert result.result["chunks"] == chunks
    assert result.result["count"] == 1


def test_search_documents_passes_through_top_k_and_rerank():
    rag = FakeRagLeap(chunks=[])
    config = SearchConfig(rag=rag)

    search_documents(config, "query", top_k=10, rerank=True)

    assert rag.retrieve_calls == [
        {"query": "query", "top_k": 10, "hybrid": True, "rerank": True, "metadata_filter": None}
    ]


def test_search_documents_always_uses_hybrid_retrieval():
    rag = FakeRagLeap(chunks=[])
    config = SearchConfig(rag=rag)

    search_documents(config, "query")

    assert rag.retrieve_calls[0]["hybrid"] is True


def test_search_documents_returns_empty_result_for_no_matches():
    rag = FakeRagLeap(chunks=[])
    config = SearchConfig(rag=rag)

    result = search_documents(config, "no matches for this")

    assert result.success is True
    assert result.result["chunks"] == []
    assert result.result["count"] == 0


def test_search_documents_catches_unexpected_errors():
    rag = FakeRagLeap(raise_error=RuntimeError("vector backend unreachable"))
    config = SearchConfig(rag=rag)

    result = search_documents(config, "query")

    assert result.success is False
    assert "vector backend unreachable" in result.error


def test_make_search_tool_returns_bound_tool():
    rag = FakeRagLeap(chunks=[{"text": "bound result"}])
    config = SearchConfig(rag=rag)
    tool = make_search_tool(config)

    assert tool.name == "search_documents"
    result = tool.call(query="test")

    assert result.success is True
    assert result.result["chunks"] == [{"text": "bound result"}]


def test_make_search_tool_has_valid_openai_schema():
    config = SearchConfig(rag=FakeRagLeap())
    tool = make_search_tool(config)
    schema = tool.to_openai_schema()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "search_documents"
    assert "query" in schema["function"]["parameters"]["properties"]
    assert schema["function"]["parameters"]["required"] == ["query"]


def test_make_search_tool_has_valid_gemini_schema():
    config = SearchConfig(rag=FakeRagLeap())
    tool = make_search_tool(config)
    schema = tool.to_gemini_schema()

    assert schema["name"] == "search_documents"
    assert "parameters" in schema


def test_search_documents_passes_filename_as_metadata_filter():
    rag = FakeRagLeap(chunks=[])
    config = SearchConfig(rag=rag)

    search_documents(config, "query", filename="report.pdf")

    assert rag.retrieve_calls == [
        {"query": "query", "top_k": 5, "hybrid": True, "rerank": False, "metadata_filter": {"filename": "report.pdf"}}
    ]


def test_search_documents_without_filename_passes_no_metadata_filter():
    """Confirms the default (no filename=) path is unchanged - the
    real regression risk this test guards against is filename=None
    somehow producing metadata_filter={"filename": None}, which would
    silently break every existing caller that doesn't pass filename=."""
    rag = FakeRagLeap(chunks=[])
    config = SearchConfig(rag=rag)

    search_documents(config, "query")

    assert rag.retrieve_calls[0]["metadata_filter"] is None


def test_make_search_tool_schema_includes_optional_filename():
    config = SearchConfig(rag=FakeRagLeap())
    tool = make_search_tool(config)
    schema = tool.to_openai_schema()

    props = schema["function"]["parameters"]["properties"]
    assert "filename" in props
    assert schema["function"]["parameters"]["required"] == ["query"]


def test_make_search_tool_call_with_filename_passes_through():
    rag = FakeRagLeap(chunks=[{"text": "scoped result"}])
    config = SearchConfig(rag=rag)
    tool = make_search_tool(config)

    result = tool.call(query="test", filename="notes.txt")

    assert result.success is True
    assert result.result["chunks"] == [{"text": "scoped result"}]
