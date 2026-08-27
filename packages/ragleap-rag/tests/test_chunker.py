"""Tests for TextChunker — chunk windowing/overlap, and token_count
accuracy (real tiktoken counts when available, honest word-count
fallback with token_count_is_exact=False when tiktoken can't load)."""
import pytest

from ragleap.chunker import TextChunker


def test_chunk_text_basic_windowing():
    chunker = TextChunker(chunk_size=5, chunk_overlap=1)
    chunks = chunker.chunk_text("the quick brown fox jumps over the lazy dog today")

    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert chunks[0]["text"] == "the quick brown fox jumps"
    assert chunks[1]["text"] == "jumps over the lazy dog"


def test_chunk_text_empty_input_returns_empty_list():
    chunker = TextChunker()
    assert chunker.chunk_text("") == []
    assert chunker.chunk_text("   ") == []


def test_chunk_text_raises_on_invalid_overlap():
    with pytest.raises(ValueError):
        TextChunker(chunk_size=10, chunk_overlap=10)


def test_chunk_text_reports_token_count_is_exact_flag():
    chunker = TextChunker(chunk_size=10, chunk_overlap=2)
    chunks = chunker.chunk_text("some real text to chunk here for this test")

    for c in chunks:
        assert "token_count" in c
        assert "token_count_is_exact" in c
        assert isinstance(c["token_count_is_exact"], bool)
        assert c["token_count"] > 0


def test_chunk_text_token_count_matches_tiktoken_when_exact():
    chunker = TextChunker(chunk_size=50, chunk_overlap=5)
    chunks = chunker.chunk_text("hello world this is a test")
    chunk = chunks[0]

    if chunk["token_count_is_exact"]:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        assert chunk["token_count"] == len(enc.encode(chunk["text"]))
    else:
        assert chunk["token_count"] == len(chunk["text"].split())


def test_chunk_text_fallback_word_count_when_tiktoken_unavailable(monkeypatch):
    """Forces the fallback path regardless of the real environment, so
    this test doesn't depend on network availability at CI/test time --
    confirms the fallback contract directly (is_exact=False, count ==
    whitespace split), the same behavior the field had before this fix."""
    import ragleap.chunker as chunker_module

    monkeypatch.setattr(chunker_module, "_TIKTOKEN_AVAILABLE", False)

    chunker = chunker_module.TextChunker(chunk_size=10, chunk_overlap=2)
    chunks = chunker.chunk_text("a simple test phrase for the fallback path")

    for c in chunks:
        assert c["token_count_is_exact"] is False
        assert c["token_count"] == len(c["text"].split())


def test_chunk_text_fallback_on_encoding_load_failure(monkeypatch):
    """tiktoken installed but its encoding can't load (e.g. no network
    egress to fetch the BPE rank file on first use) -- must degrade to
    the honest fallback, not raise."""
    import ragleap.chunker as chunker_module

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated: no network egress to fetch encoding")

    monkeypatch.setattr(chunker_module, "_TIKTOKEN_AVAILABLE", True)
    monkeypatch.setattr(chunker_module.tiktoken, "get_encoding", _raise, raising=False)
    chunker_module._encoding_cache.clear()

    chunker = chunker_module.TextChunker(chunk_size=10, chunk_overlap=2)
    chunks = chunker.chunk_text("a phrase whose encoding load will fail")

    for c in chunks:
        assert c["token_count_is_exact"] is False
        assert c["token_count"] == len(c["text"].split())
