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


def test_ask_stream_respects_metadata_filter(rag):
    rag.ingest_text(filename="a.txt", text="Acme tenant content about pricing.", metadata={"tenant": "acme"})
    rag.ingest_text(filename="b.txt", text="Globex tenant content about pricing.", metadata={"tenant": "globex"})

    pieces = list(rag.ask_stream("pricing", metadata_filter={"tenant": "acme"}, hybrid=False))
    assert "".join(pieces) == "This is a fake streamed answer."
    # No direct sources field on ask_stream's return, but this confirms
    # the call succeeds end-to-end with metadata_filter wired through.


def test_ask_stream_rerank_true_calls_reranker(rag, monkeypatch):
    from ragleap.reranking import RerankerService

    rag.ingest_text(filename="a.txt", text="Content about apples.")
    rag.ingest_text(filename="b.txt", text="Content about spaceships.")

    call_log = []

    def fake_rerank(self, query, chunks, top_k):
        call_log.append(len(chunks))
        return chunks[:top_k]

    monkeypatch.setattr(RerankerService, "rerank", fake_rerank)
    list(rag.ask_stream("something", rerank=True, top_k=1, hybrid=False))

    assert len(call_log) == 1


def test_ask_stream_rerank_false_never_calls_reranker(rag, monkeypatch):
    from ragleap.reranking import RerankerService

    rag.ingest_text(filename="a.txt", text="Some content.")

    called = {"value": False}

    def fake_rerank(self, query, chunks, top_k):
        called["value"] = True
        return chunks[:top_k]

    monkeypatch.setattr(RerankerService, "rerank", fake_rerank)
    list(rag.ask_stream("a question", rerank=False))

    assert called["value"] is False
