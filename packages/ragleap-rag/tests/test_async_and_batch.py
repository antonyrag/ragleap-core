"""Tests for async ingest/ask methods and ingest_batch() concurrent
mixed-type ingestion with partial-success semantics."""
import pytest


@pytest.mark.asyncio
async def test_aingest_text_works(rag):
    result = await rag.aingest_text(filename="a.txt", text="Some async content.")
    assert result.chunks_stored >= 1


@pytest.mark.asyncio
async def test_aask_works(rag):
    await rag.aingest_text(filename="a.txt", text="RagLeap supports async operations.")
    answer = await rag.aask("Does it support async?")
    assert answer["provider_used"] == "gemini"


@pytest.mark.asyncio
async def test_aask_stream_yields_pieces(rag):
    await rag.aingest_text(filename="a.txt", text="Some content.")
    pieces = []
    async for piece in rag.aask_stream("A question"):
        pieces.append(piece)
    assert "".join(pieces) == "This is a fake streamed answer."


@pytest.mark.asyncio
async def test_ingest_batch_all_succeed(rag):
    results = await rag.ingest_batch([
        {"type": "file", "filename": "a.txt", "raw_bytes": b"content one"},
        {"type": "file", "filename": "b.txt", "raw_bytes": b"content two"},
    ])
    assert len(results) == 2
    assert all(r["success"] for r in results)
    assert all(r["error"] is None for r in results)


@pytest.mark.asyncio
async def test_ingest_batch_partial_failure_does_not_block_others(rag):
    results = await rag.ingest_batch([
        {"type": "file", "filename": "good.txt", "raw_bytes": b"real content"},
        {"type": "not-a-real-type", "filename": "bad.txt", "raw_bytes": b"x"},
        {"type": "file", "filename": "also-good.txt", "raw_bytes": b"more real content"},
    ])
    assert len(results) == 3
    assert results[0]["success"] is True
    assert results[1]["success"] is False
    assert "Unknown batch item type" in results[1]["error"]
    assert results[2]["success"] is True


@pytest.mark.asyncio
async def test_ingest_batch_preserves_input_order(rag):
    results = await rag.ingest_batch([
        {"type": "file", "filename": f"doc{i}.txt", "raw_bytes": f"content {i}".encode()}
        for i in range(5)
    ])
    assert len(results) == 5
    assert all(r["success"] for r in results)
