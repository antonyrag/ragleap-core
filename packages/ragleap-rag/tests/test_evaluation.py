"""Tests for rag.evaluate() - deterministic retrieval hit-rate, keyword
coverage, and citation groundedness checks. Not testing real semantic
quality (the fake embedder/generator have none) - testing that the
scoring logic itself is correct, using real Postgres full-text search
for retrieval and the fake generator's real prompt-echo behavior to
create genuinely checkable keyword overlap."""
import pytest


def test_evaluate_requires_at_least_one_case(rag):
    with pytest.raises(ValueError):
        rag.evaluate([])


def test_evaluate_retrieval_hit_rate_all_hits(rag):
    rag.ingest_text("bananas.txt", "This document is about bananas and tropical fruit.")
    rag.ingest_text("spaceships.txt", "This document is about spaceships and rockets.")

    result = rag.evaluate([
        {"query": "bananas", "expected_document": "bananas.txt"},
        {"query": "spaceships", "expected_document": "spaceships.txt"},
    ], hybrid=True)

    assert result["retrieval_hit_rate"] == 1.0
    assert len(result["results"]) == 2


def test_evaluate_retrieval_hit_rate_partial_miss(rag):
    rag.ingest_text("bananas.txt", "This document is about bananas and tropical fruit.")

    result = rag.evaluate([
        {"query": "bananas", "expected_document": "bananas.txt"},
        {"query": "bananas", "expected_document": "nonexistent-doc.txt"},
    ], hybrid=True)

    assert result["retrieval_hit_rate"] == 0.5


def test_evaluate_keyword_coverage_uses_real_answer_content(rag):
    """The fake generator echoes the prompt's tail, which includes the
    query - so a keyword drawn from the query genuinely appears in the
    fake answer, making this a real test of the coverage calculation,
    not a coincidence."""
    rag.ingest_text("a.txt", "Some content about testing things.")

    result = rag.evaluate([
        {"query": "Tell me about bananas specifically", "expected_keywords": ["bananas"]},
    ])

    assert result["keyword_coverage_rate"] == 1.0
    assert result["results"][0]["keywords_found"] == ["bananas"]


def test_evaluate_keyword_coverage_partial(rag):
    rag.ingest_text("a.txt", "Some content.")

    result = rag.evaluate([
        {"query": "Tell me about bananas", "expected_keywords": ["bananas", "spaceships", "rockets"]},
    ])

    # Only "bananas" appears in the query (which the fake generator echoes)
    assert result["keyword_coverage_rate"] == pytest.approx(1 / 3)


def test_evaluate_groundedness_when_keyword_in_cited_chunk(rag):
    """Ingest text containing 'bananas' so it ends up in the cited
    chunk's text_preview - if the fake answer also mentions 'bananas'
    (via the query echo), groundedness should be 1.0 since the
    keyword genuinely appears in both."""
    rag.ingest_text("bananas.txt", "This document contains real information about bananas and fruit.")

    result = rag.evaluate([
        {"query": "Tell me about bananas", "expected_keywords": ["bananas"]},
    ], hybrid=True)

    assert result["groundedness_rate"] == 1.0


def test_evaluate_returns_none_for_metrics_with_no_applicable_cases(rag):
    rag.ingest_text("a.txt", "Some content.")

    result = rag.evaluate([{"query": "a question with no expectations set"}])

    assert result["retrieval_hit_rate"] is None
    assert result["keyword_coverage_rate"] is None
    assert result["groundedness_rate"] is None
    assert len(result["results"]) == 1


def test_evaluate_passes_through_ask_kwargs(rag):
    rag.ingest_text("a.txt", "Acme tenant content.", metadata={"tenant": "acme"})
    rag.ingest_text("b.txt", "Globex tenant content.", metadata={"tenant": "globex"})

    result = rag.evaluate(
        [{"query": "tenant content", "expected_document": "a.txt"}],
        metadata_filter={"tenant": "acme"},
        hybrid=False,
    )

    assert result["results"][0]["sources"] == ["a.txt"]
