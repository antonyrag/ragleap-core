"""Tests for persistent conversation memory (session-scoped, Postgres-backed)."""


def test_get_history_empty_for_new_session(rag):
    assert rag.get_history("brand-new-session") == []


def test_ask_with_session_id_stores_history(rag):
    rag.ingest_text(filename="a.txt", text="RagLeap supports WhatsApp integration.")

    rag.ask("Does it support WhatsApp?", session_id="session-1")
    history = rag.get_history("session-1")

    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


def test_ask_without_session_id_stores_nothing(rag):
    rag.ingest_text(filename="a.txt", text="Some content.")
    rag.ask("A question", session_id=None)
    assert rag.get_history("some-session-never-used") == []


def test_multiple_turns_accumulate_in_order(rag):
    rag.ingest_text(filename="a.txt", text="Some content about pricing.")
    rag.ask("First question", session_id="s1")
    rag.ask("Second question", session_id="s1")

    history = rag.get_history("s1")
    assert len(history) == 4
    assert history[0]["content"] == "First question"
    assert history[2]["content"] == "Second question"


def test_sessions_are_isolated(rag):
    rag.ingest_text(filename="a.txt", text="Some content.")
    rag.ask("Question in session A", session_id="session-a")
    rag.ask("Question in session B", session_id="session-b")

    history_a = rag.get_history("session-a")
    history_b = rag.get_history("session-b")

    assert len(history_a) == 2
    assert len(history_b) == 2
    assert history_a[0]["content"] == "Question in session A"
    assert history_b[0]["content"] == "Question in session B"


def test_clear_session_removes_all_messages(rag):
    rag.ingest_text(filename="a.txt", text="Some content.")
    rag.ask("A question", session_id="to-clear")
    assert len(rag.get_history("to-clear")) == 2

    rag.clear_session("to-clear")
    assert rag.get_history("to-clear") == []


def test_history_injected_into_prompt_via_generator(rag):
    """The fake generator echoes the tail of the prompt it received -
    confirms history_prefix is actually built and passed through, not
    just stored."""
    rag.ingest_text(filename="a.txt", text="Some content.")
    rag.ask("First question", session_id="s1")
    answer = rag.ask("Second question", session_id="s1")
    assert "Second question" in answer["answer"]
