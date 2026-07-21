"""
ragleap-rag: a fast, honest, self-hosted RAG engine.

    from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

    rag = RagLeap(
        database_url="postgresql://user:pass@localhost/mydb",
        embedder=EmbeddingConfig(provider="gemini", api_key="..."),
        primary=ProviderConfig(provider="gemini", api_key="..."),
    )
    rag.init_schema()                  # one-time, idempotent

    result = rag.ingest("doc.pdf", raw_bytes)
    print(result.document_id, result.chunks_stored)

    answer = rag.ask("What does this document say about X?")
    print(answer["answer"], answer["sources"], answer["usage"])
"""
import uuid
import logging
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional

from ragleap.chunker import TextChunker
from ragleap.embedding import EmbeddingService, EmbeddingConfig
from ragleap.retrieval import VectorRetrievalService
from ragleap.generation import GenerationService, ProviderConfig
from ragleap.parsers import extract_text
from ragleap.memory import ConversationMemory
from ragleap.reranking import RerankerService
from ragleap.db import ConnectionPool
from ragleap.cache import QueryEmbeddingCache
from ragleap import schema as _schema

logger = logging.getLogger(__name__)

__version__ = "0.4.2"
__all__ = ["RagLeap", "ProviderConfig", "EmbeddingConfig", "IngestResult"]


@dataclass
class IngestResult:
    document_id: str
    chunks_stored: int


class RagLeap:
    """
    The main entry point for ragleap-rag. Wires together chunking,
    embedding, hybrid retrieval, and generation (with fallback,
    streaming, and token usage reporting) over a PostgreSQL + pgvector
    database you control.
    """

    def __init__(
        self,
        database_url: str,
        primary: ProviderConfig,
        embedder: EmbeddingConfig,
        fallbacks: Optional[List[ProviderConfig]] = None,
        default_temperature: float = 0.3,
        default_max_tokens: int = 1024,
        max_context_chars: int = 12000,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        cache_enabled: bool = True,
        cache_max_size: int = 1000,
    ):
        self.database_url = database_url
        self.embedding_dimensions = embedder.dimensions
        self._pool = ConnectionPool(database_url)

        self._chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._embedder = EmbeddingService(embedder)
        self._retriever = VectorRetrievalService(pool=self._pool, embedding_dimensions=embedder.dimensions)
        self._memory = ConversationMemory(pool=self._pool)
        self._reranker = None  # lazy-loaded on first rerank=True call
        self._cache_enabled = cache_enabled
        self._query_cache = QueryEmbeddingCache(max_size=cache_max_size) if cache_enabled else None
        self._generator = GenerationService(
            primary=primary,
            fallbacks=fallbacks,
            default_temperature=default_temperature,
            default_max_tokens=default_max_tokens,
            max_context_chars=max_context_chars,
        )

    def init_schema(self) -> None:
        """Create the required tables/indexes if they don't already exist. Idempotent."""
        _schema.init_schema(self.database_url, dimensions=self.embedding_dimensions)

    def _embed_query_cached(self, query: str) -> Optional[List[float]]:
        """Embed a query, using the cache if enabled. Cache key is
        (query text, embedding model) - safe across different queries
        and different embedder configs on the same instance."""
        if self._cache_enabled:
            cached = self._query_cache.get(query, self._embedder.model)
            if cached is not None:
                return cached

        embedding = self._embedder.embed_text(query)

        if self._cache_enabled and embedding is not None:
            self._query_cache.set(query, self._embedder.model, embedding)

        return embedding

    def cache_stats(self) -> dict:
        """Return query embedding cache stats: hits, misses, hit_rate, size.
        Returns all zeros if caching is disabled."""
        if not self._cache_enabled:
            return {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "enabled": False}
        stats = self._query_cache.stats()
        stats["enabled"] = True
        return stats

    def ingest(self, filename: str, raw_bytes: bytes) -> IngestResult:
        """
        Extract text (from .txt/.pdf/.docx bytes), chunk, embed, and
        store it. Returns an IngestResult with the new document_id and
        chunk count.
        """
        text = extract_text(filename, raw_bytes)
        return self.ingest_text(filename, text)

    def ingest_text(self, filename: str, text: str) -> IngestResult:
        """Same as ingest(), but for text you've already extracted yourself."""
        chunks = self._chunker.chunk_text(text)
        if not chunks:
            raise ValueError("No chunks produced from input text — is it empty?")

        document_id = str(uuid.uuid4())
        with self._pool.get_connection() as conn:
          try:
            cur = conn.cursor()
            cur.execute("INSERT INTO documents (id, filename) VALUES (%s, %s)", (document_id, filename))

            stored = 0
            for chunk in chunks:
                embedding = self._embedder.embed_text(chunk["text"])
                if embedding is None:
                    logger.warning(f"Skipping chunk {chunk['chunk_index']} — embedding failed")
                    continue

                embedding_literal = "[" + ",".join(str(float(x)) for x in embedding) + "]"
                cur.execute(
                    """
                    INSERT INTO chunks (document_id, document_name, chunk_index, text, token_count, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s::vector)
                    """,
                    (document_id, filename, chunk["chunk_index"], chunk["text"], chunk["token_count"], embedding_literal),
                )
                stored += 1

            if stored == 0:
                conn.rollback()
                raise ValueError(f"All {len(chunks)} chunk(s) failed to embed — nothing was stored.")

            conn.commit()
            cur.close()
            logger.info(f"Ingested '{filename}': {stored}/{len(chunks)} chunks stored")
            return IngestResult(document_id=document_id, chunks_stored=stored)
          except Exception:
            conn.rollback()
            raise

    def ask(
        self,
        query: str,
        top_k: int = 5,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        hybrid: bool = True,
        session_id: Optional[str] = None,
        rerank: bool = False,
    ) -> Dict:
        """
        Answer a question grounded in previously ingested documents.
        Pass session_id to enable persistent, multi-turn conversation
        memory (Postgres-backed) — prior turns in that session are
        injected as context. Omit it for a fully stateless call.
        Returns: {"answer": str, "sources": List[str], "provider_used": str,
                  "usage": dict|None, "chunks_sent": int}
        """
        query_embedding = self._embed_query_cached(query)
        if query_embedding is None:
            return {"answer": "Sorry, I couldn't process your question (embedding failed).",
                    "sources": [], "provider_used": None, "usage": None, "chunks_sent": 0}

        pool_size = top_k * 4 if rerank else top_k
        if hybrid:
            chunks = self._retriever.search_hybrid_chunks(query, query_embedding, top_k=pool_size)
        else:
            chunks = self._retriever.search_similar_chunks(query_embedding, top_k=pool_size)

        if rerank and chunks:
            if self._reranker is None:
                self._reranker = RerankerService()
            chunks = self._reranker.rerank(query, chunks, top_k=top_k)

        history_prefix = self._memory.build_history_prompt(session_id) if session_id else ""

        result = self._generator.generate_answer(
            query, chunks, temperature=temperature, system_prompt=system_prompt,
            max_tokens=max_tokens, history_prefix=history_prefix,
        )

        if session_id:
            self._memory.add_message(session_id, "user", query)
            self._memory.add_message(session_id, "assistant", result["answer"])

        return result

    def ask_stream(
        self,
        query: str,
        top_k: int = 5,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        hybrid: bool = True,
        session_id: Optional[str] = None,
    ) -> Iterator[str]:
        """Same as ask(), but yields the answer incrementally as it's
        generated. If session_id is set, the full assembled answer is
        stored to memory once streaming completes."""
        query_embedding = self._embed_query_cached(query)
        if query_embedding is None:
            yield "Sorry, I couldn't process your question (embedding failed)."
            return

        if hybrid:
            chunks = self._retriever.search_hybrid_chunks(query, query_embedding, top_k=top_k)
        else:
            chunks = self._retriever.search_similar_chunks(query_embedding, top_k=top_k)

        history_prefix = self._memory.build_history_prompt(session_id) if session_id else ""

        pieces = []
        for piece in self._generator.generate_answer_stream(
            query, chunks, temperature=temperature, system_prompt=system_prompt,
            max_tokens=max_tokens, history_prefix=history_prefix,
        ):
            pieces.append(piece)
            yield piece

        if session_id:
            self._memory.add_message(session_id, "user", query)
            self._memory.add_message(session_id, "assistant", "".join(pieces))

    def get_history(self, session_id: str) -> List[Dict]:
        """Return the stored conversation history for a session, oldest first."""
        return self._memory.get_history(session_id)

    def clear_session(self, session_id: str) -> None:
        """Delete a session and its full message history."""
        self._memory.clear_session(session_id)
