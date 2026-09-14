"""
eval_graph_compare.py — for issue #153 (eval framework)

Lets ragleap-rag's real evaluate()/evaluate_case() (src/ragleap/evaluation.py)
score ragleap_graph.GraphRetriever the same way it already scores plain
ragleap-rag, so the two can be compared side-by-side on the same labeled
test cases.

Confirmed against real source (both files fetched from the VPS):
  - evaluate_case() calls `rag.ask(query, **ask_kwargs)` and reads:
      answer["sources"]            -> list, checked via `expected_document in sources`
      answer["answer"]             -> str, keyword-searched
      answer["citations"]          -> list of dicts, each read via c.get("text_preview", "")
  - GraphRetriever.retrieve(query, top_k=5, namespace=None, metadata_filter=None)
    returns:
      {
        "chunks": [...],            # dicts, each with "document_name" (confirmed
                                     # 2026-09-13 via a live run: this is what
                                     # ragleap-rag's sources list is actually
                                     # built from, NOT document_id - an earlier
                                     # version of this file assumed document_id,
                                     # which was a real, confirmed bug)
        "query_entities": [...],
        "graph_context": {
            "related_documents": [...],   # dicts with "document_name" (same
                                           # convention) + "already_in_vector_results"
            "related_entities": [...],
        },
        "citations": [...],         # already built by GraphRetriever._build_citations();
                                     # matches evaluate_case()'s "text_preview" convention
                                     # by field-name design, so passed through unchanged
        "retrieval_method": "hybrid_vector_graph" | "graph_only",
      }

Chunk dicts' text field is confirmed "text" -- used consistently across
chunker.py (the field is created there), __init__.py, generation.py, and
reranking.py. Since GraphRetriever.retrieve()'s chunks come from
self._rag.retrieve() (the same RagLeap instance/pipeline), they carry
the same shape.

Design choice: retrieve() returns retrieved context only, no generated
answer. GraphRetrieverAskAdapter retrieves via the graph, then generates
an answer using a caller-supplied `generate_fn` — pass the SAME
LLM/provider call plain ragleap-rag's real .ask() uses internally, so the
comparison isolates retrieval quality and doesn't also compare generation
quality between two different models/prompts.
"""

import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class GraphRetrieverAskAdapter:
    """
    Wraps a ragleap_graph.GraphRetriever so it exposes an .ask() method
    compatible with ragleap-rag's real evaluate()/evaluate_case().
    """

    def __init__(
        self,
        graph_retriever: Any,
        generate_fn: Callable[[str, str], str],
        top_k: int = 5,
    ):
        """
        graph_retriever: a constructed ragleap_graph.retrieval.GraphRetriever
            (already wired to a live GraphIndex + RagLeap instance).
        generate_fn: (query, context_str) -> answer_str. Pass the same LLM
            call plain ragleap-rag's real .ask() uses, so only retrieval
            differs between the two arms of the comparison.
        top_k: default retrieval depth, overridable per-call.
        """
        self._retriever = graph_retriever
        self._generate_fn = generate_fn
        self._top_k = top_k

    def ask(self, query: str, **kwargs) -> Dict[str, Any]:
        top_k = kwargs.pop("top_k", self._top_k)
        namespace = kwargs.pop("namespace", None)
        metadata_filter = kwargs.pop("metadata_filter", None)

        retrieval = self._retriever.retrieve(
            query, top_k=top_k, namespace=namespace, metadata_filter=metadata_filter
        )

        context_str = self._build_context_str(retrieval)
        answer_text = self._generate_fn(query, context_str)
        sources = self._extract_sources(retrieval)

        return {
            "answer": answer_text,
            "sources": sources,
            "citations": retrieval.get("citations", []),
            # kept for debugging/analysis only — evaluate_case() doesn't read these
            "_retrieval_method": retrieval.get("retrieval_method"),
            "_query_entities": retrieval.get("query_entities"),
        }

    @staticmethod
    def _extract_sources(retrieval: Dict[str, Any]) -> List[str]:
        """
        Returns document_name/filename, NOT document_id - confirmed via a
        live run (2026-09-13) that ragleap-rag.GenerationService.generate_answer()
        builds its own sources list from document_name (see generation.py:
        sources = list({c.get("document_name") for c in trimmed})), so this
        adapter must match that convention or expected_document in sources
        checks silently fail regardless of whether retrieval actually
        succeeded - a real bug this exact function had before this fix,
        caught by a live end-to-end run, not the offline mocks (which
        happened to use consistent identifiers on both sides by luck).

        document_name is confirmed present on both chunks and
        graph_context.related_documents (retrieval.py passes
        find_documents_by_entities()'s output through unmodified, and
        that method's own query aliases coalesce(d.title, '') AS document_name).
        Union of both: a document surfaced only via graph traversal
        (not vector search) is exactly the case this eval exists to
        measure, so it must count as a source, not be dropped.
        """
        chunk_names = {
            c.get("document_name") for c in retrieval.get("chunks", []) if c.get("document_name")
        }
        graph_names = {
            d.get("document_name")
            for d in retrieval.get("graph_context", {}).get("related_documents", [])
            if d.get("document_name")
        }
        return sorted(chunk_names | graph_names)

    @staticmethod
    def _extract_chunk_text(chunk: Dict[str, Any]) -> str:
        """
        Confirmed: chunk dicts use "text" (chunker.py creates it under
        that key; __init__.py, generation.py, and reranking.py all read
        it the same way).
        """
        return chunk.get("text", "")

    def _build_context_str(self, retrieval: Dict[str, Any]) -> str:
        parts = []

        related_entities = retrieval.get("graph_context", {}).get("related_entities", [])
        if related_entities:
            parts.append(f"[Related entities]\n{related_entities}")

        related_documents = retrieval.get("graph_context", {}).get("related_documents", [])
        for doc in related_documents:
            if doc.get("already_in_vector_results"):
                continue  # avoid duplicating context already covered by a chunk below
            parts.append(f"[Related document: {doc.get('document_name', 'unknown')}]\n{doc}")

        for chunk in retrieval.get("chunks", []):
            source = chunk.get("document_name", "unknown")
            text = self._extract_chunk_text(chunk)
            parts.append(f"[Source: {source}]\n{text}")

        return "\n\n".join(parts)


def compare_retrieval_methods(
    vector_rag: Any,
    graph_adapter: "GraphRetrieverAskAdapter",
    test_cases: List[Dict[str, Any]],
    evaluate_fn: Callable[..., Dict[str, Any]],
    **ask_kwargs,
) -> Dict[str, Any]:
    """
    Runs the same labeled test_cases (EvalCase shape: query,
    expected_document, expected_keywords) through both plain ragleap-rag
    (vector_rag, must expose .ask()) and graph-augmented retrieval
    (graph_adapter), scoring both with the SAME evaluate_fn — pass
    ragleap.evaluation.evaluate directly so both arms are scored with
    identical logic.

    Returns:
        {
          "vector": {...evaluate() output for plain ragleap-rag...},
          "graph":  {...evaluate() output for graph-augmented retrieval...},
          "delta":  {metric_name: graph_value - vector_value, ...}
                    (only for metrics that are non-None on both sides —
                    evaluate()'s rates can be None when no case exercises
                    that dimension, and None - None isn't meaningful)
        }
    """
    vector_result = evaluate_fn(vector_rag, test_cases, **ask_kwargs)
    graph_result = evaluate_fn(graph_adapter, test_cases, **ask_kwargs)

    metrics = ("retrieval_hit_rate", "keyword_coverage_rate", "groundedness_rate")
    delta = {
        m: graph_result[m] - vector_result[m]
        for m in metrics
        if vector_result.get(m) is not None and graph_result.get(m) is not None
    }

    return {"vector": vector_result, "graph": graph_result, "delta": delta}


# ---------------------------------------------------------------------------
# Validation against the REAL evaluate()/evaluate_case() (copied verbatim
# from the fetched source, not reimplemented) — run directly:
#   python eval_graph_compare.py
# Chunk/graph_context shapes below match what retrieval.py's own code
# confirms (document_name on both chunks and related_documents); the one
# remaining unconfirmed piece (chunk text field name) is exercised via
# the "text" key as a stand-in — swap in the real key once known.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from ragleap.evaluation import evaluate  # the real module - was importing a
    # nonexistent real_evaluation.py shim before this fix, confirmed broken
    # (found via a #153 documentation-claims/status audit)

    class _MockGraphRetriever:
        """Stands in for ragleap_graph.retrieval.GraphRetriever."""
        def retrieve(self, query, top_k=5, namespace=None, metadata_filter=None):
            return {
                "chunks": [
                    {"document_name": "doc1", "text": "Acme Corporation was founded in 1998."},
                ],
                "query_entities": ["Acme Corporation"],
                "graph_context": {
                    "related_documents": [
                        {"document_name": "doc2", "already_in_vector_results": False},
                    ],
                    "related_entities": ["Alice (CEO)"],
                },
                "citations": [
                    {"text_preview": "Acme Corporation was founded in 1998.", "source": "doc1"},
                    {"text_preview": "Alice is the CEO of Acme.", "source": "doc2"},
                ],
                "retrieval_method": "hybrid_vector_graph",
            }

    def _mock_generate_fn(query, context_str):
        # Stand-in LLM: answer using both vector chunk AND graph-surfaced fact
        return "Acme Corporation was founded in 1998 and Alice is its CEO."

    class _MockVectorRag:
        """Stands in for plain ragleap-rag's real .ask() - vector-only,
        so it can't see the graph-surfaced 'Alice is CEO' fact from doc2."""
        def ask(self, query, **kwargs):
            return {
                "answer": "Acme Corporation was founded in 1998.",
                "sources": ["doc1"],
                "citations": [
                    {"text_preview": "Acme Corporation was founded in 1998.", "source": "doc1"},
                ],
            }

    test_cases = [
        {
            "query": "Who founded Acme and who runs it?",
            "expected_document": "doc2",  # only findable via graph traversal in this mock
            "expected_keywords": ["1998", "Alice"],
        },
    ]

    adapter = GraphRetrieverAskAdapter(_MockGraphRetriever(), _mock_generate_fn)
    result = compare_retrieval_methods(_MockVectorRag(), adapter, test_cases, evaluate)

    print("vector:", result["vector"])
    print("graph: ", result["graph"])
    print("delta: ", result["delta"])

    assert result["vector"]["retrieval_hit_rate"] == 0.0, "vector-only should miss doc2"
    assert result["graph"]["retrieval_hit_rate"] == 1.0, "graph should surface doc2 via traversal"
    assert result["graph"]["keyword_coverage_rate"] > result["vector"]["keyword_coverage_rate"]
    print("\nOK - adapter scores correctly against the REAL evaluate()/evaluate_case(), using document_name consistently on both sides (the real bug this file had before 2026-09-13).")
