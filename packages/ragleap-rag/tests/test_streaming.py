"""Tests for ask_stream() — sync generator, incremental piece yielding,
and history storage once streaming completes."""


def test_ask_stream_yields_and_assembles_full_answer(rag):
    rag.ingest_text(filename="a.txt", text="Some content.")
    pieces = list(rag.ask_stream("A question"))
    assert pieces == ["This ", "is ", "a ", "fake ", "streamed ", "answer."]
    assert "".join(pieces) == "This is a fake streamed answer."


def test_ask_stream_stores_full_answer_to_history_when_session_id_given(rag):
    rag.ingest_text(filename="a.txt", text="Some content.")
    list(rag.ask_stream("A question", session_id="stream-session"))

    history = rag.get_history("stream-session")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "A question"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "This is a fake streamed answer."


def test_ask_stream_no_session_id_stores_nothing(rag):
    rag.ingest_text(filename="a.txt", text="Some content.")
    list(rag.ask_stream("A question"))
    assert rag.get_history("never-used-session") == []
