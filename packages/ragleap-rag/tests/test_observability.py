"""Tests for on_ingest/on_query/on_answer observability hooks - fire-
and-forget event emission that never breaks the actual RAG operation,
even when a hook raises."""
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from conftest import TEST_DATABASE_URL, TEST_DIMENSIONS


def _make_rag(**kwargs):
    return RagLeap(
        database_url=TEST_DATABASE_URL,
        embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
        **kwargs,
    )


def test_on_ingest_fires_with_correct_event_shape():
    events = []
    rag = _make_rag(on_ingest=[events.append])

    result = rag.ingest_text("a.txt", "Some content about testing things.")

    assert len(events) == 1
    assert events[0]["document_id"] == result.document_id
    assert events[0]["filename"] == "a.txt"
    assert events[0]["chunks_stored"] == 1
    assert events[0]["chunks_attempted"] == 1


def test_on_query_and_on_answer_fire_on_ask(rag):
    query_events = []
    answer_events = []
    rag._on_query = [query_events.append]
    rag._on_answer = [answer_events.append]

    rag.ingest_text("a.txt", "Some content.")
    rag.ask("A question", top_k=3, hybrid=True)

    assert len(query_events) == 1
    assert query_events[0]["query"] == "A question"
    assert query_events[0]["hybrid"] is True
    assert query_events[0]["top_k"] == 3
    assert query_events[0]["streaming"] is False

    assert len(answer_events) == 1
    assert answer_events[0]["provider_used"] == "gemini"
    assert answer_events[0]["streaming"] is False
    assert answer_events[0]["guardrail_blocked"] is False


def test_on_query_and_on_answer_fire_on_ask_stream(rag):
    query_events = []
    answer_events = []
    rag._on_query = [query_events.append]
    rag._on_answer = [answer_events.append]

    rag.ingest_text("a.txt", "Some content.")
    list(rag.ask_stream("A question"))

    assert len(query_events) == 1
    assert query_events[0]["streaming"] is True

    assert len(answer_events) == 1
    assert answer_events[0]["streaming"] is True
    assert answer_events[0]["answer_length"] == len("This is a fake streamed answer.")


def test_multiple_handlers_all_fire_in_order():
    calls = []
    rag = _make_rag(on_ingest=[lambda e: calls.append("first"), lambda e: calls.append("second")])

    rag.ingest_text("a.txt", "Some content.")

    assert calls == ["first", "second"]


def test_broken_hook_does_not_break_ingestion(caplog):
    import logging

    def broken_hook(event):
        raise RuntimeError("this hook is broken")

    rag = _make_rag(on_ingest=[broken_hook])

    with caplog.at_level(logging.WARNING):
        result = rag.ingest_text("a.txt", "Some content.")

    # Ingestion succeeded despite the broken hook
    assert result.chunks_stored == 1
    assert any("on_ingest" in record.message and "broken" in record.message for record in caplog.records)


def test_broken_hook_does_not_break_ask(rag):
    def broken_hook(event):
        raise RuntimeError("boom")

    rag._on_answer = [broken_hook]
    rag.ingest_text("a.txt", "Some content.")

    answer = rag.ask("A question")
    assert answer["answer"] != ""


def test_no_hooks_configured_is_a_true_no_op(rag):
    """No hooks set (the default) - fire_event should be a silent
    no-op, not an error."""
    rag.ingest_text("a.txt", "Some content.")
    answer = rag.ask("A question")
    assert answer["answer"] != ""
