"""
Lightweight, deterministic evaluation utility for ragleap-rag.

Honest scope: this is NOT an LLM-as-judge evaluation framework (like
Ragas's faithfulness/relevancy scoring) - those require careful judge-
prompt design and calibration, and belong in a separate, dedicated
tool (planned as part of ragleap-observability, which will span more
than just RAG). This module does three deterministic, measurable
checks instead:

1. Retrieval hit rate - did the expected source document actually
   appear in the retrieved chunks for a query?
2. Keyword coverage - what fraction of expected keywords appear
   (case-insensitive substring match) in the generated answer?
3. Citation groundedness - of the keywords found in the answer, what
   fraction also appear in the text of the chunks the answer actually
   cited? A low score here suggests the model may be answering from
   outside the retrieved context (a real hallucination signal, though
   still a heuristic - substring matching is not semantic understanding).

None of these three checks require an LLM call themselves, so running
an evaluation is fast and free beyond the ask() calls it makes.
"""
import logging
from typing import Dict, List, Optional, TypedDict

logger = logging.getLogger(__name__)


class EvalCase(TypedDict, total=False):
    query: str
    expected_document: Optional[str]
    expected_keywords: Optional[List[str]]


def _keyword_hits(text: str, keywords: List[str]) -> List[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def evaluate_case(rag, case: Dict, **ask_kwargs) -> Dict:
    """
    Run a single evaluation case through rag.ask() and score it.
    Returns per-case detail - see evaluate() for the aggregated form.
    """
    query = case["query"]
    expected_document = case.get("expected_document")
    expected_keywords = case.get("expected_keywords") or []

    answer = rag.ask(query, **ask_kwargs)

    retrieval_hit = None
    if expected_document is not None:
        retrieval_hit = expected_document in answer.get("sources", [])

    keyword_hits = _keyword_hits(answer.get("answer", ""), expected_keywords)
    keyword_coverage = (len(keyword_hits) / len(expected_keywords)) if expected_keywords else None

    groundedness = None
    if keyword_hits:
        cited_text = " ".join(c.get("text_preview", "") for c in answer.get("citations", []))
        grounded_hits = _keyword_hits(cited_text, keyword_hits)
        groundedness = len(grounded_hits) / len(keyword_hits)

    return {
        "query": query,
        "answer": answer.get("answer"),
        "sources": answer.get("sources", []),
        "retrieval_hit": retrieval_hit,
        "keyword_coverage": keyword_coverage,
        "keywords_found": keyword_hits,
        "groundedness": groundedness,
    }


def evaluate(rag, test_cases: List[Dict], **ask_kwargs) -> Dict:
    """
    Run a labeled test set through rag.ask() and report aggregate
    deterministic quality signals - retrieval hit rate, keyword
    coverage, and citation groundedness. Not a replacement for human
    review or a full LLM-as-judge eval framework - a fast, free,
    repeatable sanity check for catching regressions in your own
    retrieval/generation setup.

    test_cases: list of dicts, each with:
      - "query": str, required
      - "expected_document": str, optional - a document_name that
        should appear in answer["sources"] for this query
      - "expected_keywords": List[str], optional - substrings that
        should appear (case-insensitive) in the generated answer

    Returns: {
        "retrieval_hit_rate": float | None,   # None if no cases had expected_document
        "keyword_coverage_rate": float | None, # None if no cases had expected_keywords
        "groundedness_rate": float | None,     # None if no keyword hits occurred anywhere
        "results": [per-case detail dicts, see evaluate_case()],
    }
    """
    if not test_cases:
        raise ValueError("evaluate() requires at least one test case.")

    results = [evaluate_case(rag, case, **ask_kwargs) for case in test_cases]

    hit_results = [r["retrieval_hit"] for r in results if r["retrieval_hit"] is not None]
    retrieval_hit_rate = (sum(hit_results) / len(hit_results)) if hit_results else None

    coverage_results = [r["keyword_coverage"] for r in results if r["keyword_coverage"] is not None]
    keyword_coverage_rate = (sum(coverage_results) / len(coverage_results)) if coverage_results else None

    groundedness_results = [r["groundedness"] for r in results if r["groundedness"] is not None]
    groundedness_rate = (sum(groundedness_results) / len(groundedness_results)) if groundedness_results else None

    logger.info(
        f"Evaluation complete: {len(results)} cases, "
        f"retrieval_hit_rate={retrieval_hit_rate}, "
        f"keyword_coverage_rate={keyword_coverage_rate}, "
        f"groundedness_rate={groundedness_rate}"
    )

    return {
        "retrieval_hit_rate": retrieval_hit_rate,
        "keyword_coverage_rate": keyword_coverage_rate,
        "groundedness_rate": groundedness_rate,
        "results": results,
    }
