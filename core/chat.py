"""
Chat Pipeline for RagLeap Core
Wires together: query language detection -> embedding the query -> hybrid
(dense + sparse, graph-boosted) retrieval -> answer generation (blocking
or streaming).
"""
import logging
from typing import Iterator, Optional

from core.embedding import EmbeddingService
from core.retrieval import VectorRetrievalService
from core.generation import GenerationService
from core.language import language_detector

logger = logging.getLogger(__name__)


def _prepare(query: str, top_k: int, hybrid: bool):
    """Shared setup for both ask() and ask_stream(): detect language,
    embed the query, retrieve chunks. Returns (chunks, detected_language,
    embedding_failed: bool).

    hybrid=True (default) uses dense+sparse fusion (search_hybrid_chunks).
    hybrid=False uses dense-only, graph-boosted retrieval (the older
    search_similar_chunks_with_graph) — kept as an option since it's a
    cheaper query path (one search instead of two) for callers that
    don't need the sparse/keyword-matching benefit.
    """
    embedder = EmbeddingService()
    retriever = VectorRetrievalService()

    try:
        detected_language, _confidence = language_detector.detect_query_language(query)
    except Exception as e:
        logger.warning(f"Query language detection failed (non-fatal): {e}")
        detected_language = None

    query_embedding = embedder.embed_text(query)
    if query_embedding is None:
        return [], detected_language, True

    if hybrid:
        chunks = retriever.search_hybrid_chunks(query, query_embedding, top_k=top_k)
    else:
        chunks = retriever.search_similar_chunks_with_graph(query, query_embedding, top_k=top_k)

    return chunks, detected_language, False


def ask(
    query: str,
    top_k: int = 5,
    temperature: Optional[float] = None,
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    hybrid: bool = True,
) -> dict:
    """
    Answer a question grounded in previously ingested documents.
    Returns: {"answer": str, "sources": List[str], "chunks_used": int, "detected_language": str}

    temperature: overrides the generation service's default temperature for this call.
    system_prompt: overrides the default grounded-QA instructions.
    max_tokens: overrides the default max output length for this call.
    hybrid: use dense+sparse fused retrieval (default) vs. dense-only.
    """
    generator = GenerationService()
    chunks, detected_language, embedding_failed = _prepare(query, top_k, hybrid)

    if embedding_failed:
        return {
            "answer": "Sorry, I couldn't process your question (embedding failed).",
            "sources": [],
            "chunks_used": 0,
            "detected_language": detected_language,
        }

    result = generator.generate_answer(
        query, chunks, temperature=temperature, system_prompt=system_prompt, max_tokens=max_tokens
    )
    result["chunks_used"] = len(chunks)
    result["detected_language"] = detected_language
    return result


def ask_stream(
    query: str,
    top_k: int = 5,
    temperature: Optional[float] = None,
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    hybrid: bool = True,
) -> Iterator[str]:
    """
    Same as ask(), but yields the answer text incrementally as it's
    generated. Sources/chunks_used/detected_language aren't available
    until generation completes — callers needing those should use
    ask() instead.
    """
    generator = GenerationService()
    chunks, detected_language, embedding_failed = _prepare(query, top_k, hybrid)

    if embedding_failed:
        yield "Sorry, I couldn't process your question (embedding failed)."
        return

    yield from generator.generate_answer_stream(
        query, chunks, temperature=temperature, system_prompt=system_prompt, max_tokens=max_tokens
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m core.chat \"<your question>\" [--stream]")
        sys.exit(1)

    stream_mode = "--stream" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--stream"]
    question = " ".join(args)

    if stream_mode:
        print(f"\nQuestion: {question}")
        print("Answer: ", end="", flush=True)
        for piece in ask_stream(question):
            print(piece, end="", flush=True)
        print()
    else:
        result = ask(question)
        print(f"\nQuestion: {question}")
        print(f"Detected language: {result.get('detected_language')}")
        print(f"Answer: {result['answer']}")
        print(f"Sources: {result['sources']}")
        print(f"Chunks used: {result['chunks_used']}")
