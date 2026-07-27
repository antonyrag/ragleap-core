"""Tests for input_guardrails/output_guardrails - user-supplied
validation callbacks that extend (not replace) sanitization and
injection-risk detection."""
import pytest
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap.guardrails import GuardrailViolation
from conftest import TEST_DATABASE_URL, TEST_DIMENSIONS


def _make_rag(**kwargs):
    return RagLeap(
        database_url=TEST_DATABASE_URL,
        embedder=EmbeddingConfig(provider="gemini", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
        primary=ProviderConfig(provider="gemini", api_key="fake-test-key"),
        **kwargs,
    )


def test_input_guardrail_can_modify_text(database_url):
    def uppercase_guardrail(text):
        return text.upper()

    rag = _make_rag(input_guardrails=[uppercase_guardrail])
    rag.ingest_text("a.txt", "some lowercase content")

    import psycopg2
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    cur.execute("SELECT text FROM chunks ORDER BY created_at DESC LIMIT 1")
    stored_text = cur.fetchone()[0]
    cur.close()
    conn.close()

    assert stored_text == "SOME LOWERCASE CONTENT"


def test_input_guardrail_violation_aborts_ingestion_with_nothing_stored(database_url):
    def reject_banned_word(text):
        if "banned" in text.lower():
            raise GuardrailViolation("content contains a banned word")
        return text

    rag = _make_rag(input_guardrails=[reject_banned_word])

    with pytest.raises(GuardrailViolation):
        rag.ingest_text("bad.txt", "this text has a banned word in it")

    assert rag.list_documents() == []


def test_input_guardrails_run_in_order(database_url):
    calls = []

    def first(text):
        calls.append("first")
        return text

    def second(text):
        calls.append("second")
        return text

    rag = _make_rag(input_guardrails=[first, second])
    rag.ingest_text("a.txt", "some content")

    assert calls == ["first", "second"]


def test_ask_output_guardrail_passes_through_when_no_violation(rag):
    def noop_guardrail(text):
        return text

    rag._output_guardrails = [noop_guardrail]
    rag.ingest_text("a.txt", "Some content about testing.")

    answer = rag.ask("What is this about?")
    assert answer["guardrail_blocked"] is False
    assert answer["answer"] != ""


def test_ask_output_guardrail_blocks_and_replaces_answer(rag):
    def reject_everything(text):
        raise GuardrailViolation("all responses blocked for this test")

    rag._output_guardrails = [reject_everything]
    rag.ingest_text("a.txt", "Some content.")

    answer = rag.ask("A question")
    assert answer["guardrail_blocked"] is True
    assert "blocked by guardrail" in answer["answer"].lower()


def test_ask_without_output_guardrails_has_no_blocked_key(rag):
    rag.ingest_text("a.txt", "Some content.")
    answer = rag.ask("A question")
    assert "guardrail_blocked" not in answer


def test_ask_stream_guardrail_violation_logs_warning_but_still_yields(rag, caplog):
    import logging

    def reject_everything(text):
        raise GuardrailViolation("blocked for this test")

    rag._output_guardrails = [reject_everything]
    rag.ingest_text("a.txt", "Some content.")

    with caplog.at_level(logging.WARNING):
        pieces = list(rag.ask_stream("A question"))

    # Tokens are still yielded - streaming can't retroactively un-send them
    assert "".join(pieces) == "This is a fake streamed answer."
    assert any("would have blocked" in record.message for record in caplog.records)


def test_ask_stream_output_guardrail_passes_through_when_no_violation(rag):
    def noop_guardrail(text):
        return text

    rag._output_guardrails = [noop_guardrail]
    rag.ingest_text("a.txt", "Some content.")

    pieces = list(rag.ask_stream("A question"))
    assert "".join(pieces) == "This is a fake streamed answer."
