"""
Chat Pipeline for RagLeap Core
Wires together: embedding the query -> vector retrieval (graph-boosted) -> answer generation.
"""
import logging
from core.embedding import EmbeddingService
from core.retrieval import VectorRetrievalService
from core.generation import GenerationService

logger = logging.getLogger(__name__)


def ask(query: str, top_k: int = 5) -> dict:
    """
    Answer a question grounded in previously ingested documents.
    Returns: {"answer": str, "sources": List[str], "chunks_used": int}
    """
    embedder = EmbeddingService()
    retriever = VectorRetrievalService()
    generator = GenerationService()

    query_embedding = embedder.embed_text(query)
    if query_embedding is None:
        return {
            "answer": "Sorry, I couldn't process your question (embedding failed).",
            "sources": [],
            "chunks_used": 0,
        }

    chunks = retriever.search_similar_chunks_with_graph(query, query_embedding, top_k=top_k)
    result = generator.generate_answer(query, chunks)
    result["chunks_used"] = len(chunks)
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m core.chat \"<your question>\"")
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    result = ask(question)
    print(f"\nQuestion: {question}")
    print(f"Answer: {result['answer']}")
    print(f"Sources: {result['sources']}")
    print(f"Chunks used: {result['chunks_used']}")
