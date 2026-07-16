"""
Chat Pipeline for RagLeap Core
Wires together: query language detection -> embedding the query -> vector
retrieval (graph-boosted) -> answer generation.
"""
import logging
from core.embedding import EmbeddingService
from core.retrieval import VectorRetrievalService
from core.generation import GenerationService
from core.language import language_detector

logger = logging.getLogger(__name__)


def ask(query: str, top_k: int = 5) -> dict:
    """
    Answer a question grounded in previously ingested documents.
    Returns: {"answer": str, "sources": List[str], "chunks_used": int, "detected_language": str}
    """
    embedder = EmbeddingService()
    retriever = VectorRetrievalService()
    generator = GenerationService()

    try:
        detected_language, _confidence = language_detector.detect_query_language(query)
    except Exception as e:
        logger.warning(f"Query language detection failed (non-fatal): {e}")
        detected_language = None

    query_embedding = embedder.embed_text(query)
    if query_embedding is None:
        return {
            "answer": "Sorry, I couldn't process your question (embedding failed).",
            "sources": [],
            "chunks_used": 0,
            "detected_language": detected_language,
        }

    chunks = retriever.search_similar_chunks_with_graph(query, query_embedding, top_k=top_k)
    result = generator.generate_answer(query, chunks)
    result["chunks_used"] = len(chunks)
    result["detected_language"] = detected_language
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m core.chat \"<your question>\"")
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    result = ask(question)
    print(f"\nQuestion: {question}")
    print(f"Detected language: {result.get('detected_language')}")
    print(f"Answer: {result['answer']}")
    print(f"Sources: {result['sources']}")
    print(f"Chunks used: {result['chunks_used']}")
