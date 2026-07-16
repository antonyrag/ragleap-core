"""
Document Ingestion Pipeline for RagLeap Core
Wires together: chunking -> embedding -> database storage -> knowledge graph
-> language detection.
"""
import os
import logging
import uuid

from core.chunker import TextChunker
from core.embedding import EmbeddingService
from core.graph import graph_service
from core.language import language_detector

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ragleap:ragleap@localhost:5433/ragleap_core")


def _get_connection():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def ingest_document(filename: str, text: str) -> dict:
    """
    Chunk, embed, and store a document's text in the database.

    Returns: {"document_id": str, "chunks_stored": int}
    """
    chunker = TextChunker()
    embedder = EmbeddingService()

    chunks = chunker.chunk_text(text)
    if not chunks:
        raise ValueError("No chunks produced from input text — is it empty?")

    document_id = str(uuid.uuid4())

    conn = _get_connection()
    try:
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO documents (id, filename) VALUES (%s, %s)",
            (document_id, filename),
        )

        stored = 0
        for chunk in chunks:
            embedding = embedder.embed_text(chunk["text"])
            if embedding is None:
                logger.warning(f"Skipping chunk {chunk['chunk_index']} — embedding failed")
                continue

            embedding_literal = "[" + ",".join(str(float(x)) for x in embedding) + "]"

            try:
                detected_language, language_confidence = language_detector.detect_language(chunk["text"])
            except Exception as e:
                logger.warning(f"Language detection failed for chunk {chunk['chunk_index']} (non-fatal): {e}")
                detected_language, language_confidence = None, None

            cur.execute(
                """
                INSERT INTO chunks (document_id, document_name, chunk_index, text, token_count, embedding, detected_language, language_confidence)
                VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s)
                """,
                (
                    document_id,
                    filename,
                    chunk["chunk_index"],
                    chunk["text"],
                    chunk["token_count"],
                    embedding_literal,
                    detected_language,
                    language_confidence,
                ),
            )
            stored += 1

        if stored == 0:
            conn.rollback()
            raise ValueError(
                f"All {len(chunks)} chunk(s) failed to embed — nothing was stored. "
                "Check your GEMINI_API_KEY and network connectivity."
            )

        conn.commit()
        cur.close()

        logger.info(f"Ingested '{filename}': {stored}/{len(chunks)} chunks stored")

        # Knowledge graph write is best-effort — never blocks or rolls back ingestion
        try:
            graph_service.upsert_document_graph(document_id, filename, chunks)
        except Exception as e:
            logger.warning(f"Graph upsert failed for '{filename}' (non-fatal): {e}")

        return {"document_id": document_id, "chunks_stored": stored}

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m core.ingest <path-to-text-file>")
        sys.exit(1)

    filepath = sys.argv[1]
    with open(filepath, "r") as f:
        content = f.read()

    result = ingest_document(os.path.basename(filepath), content)
    print(f"✅ Ingested: {result}")
