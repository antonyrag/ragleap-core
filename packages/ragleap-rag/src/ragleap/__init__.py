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
from ragleap.cache import QueryEmbeddingCache, RedisQueryEmbeddingCache
from ragleap import sanitization as _sanitization
from ragleap import web as _web
from ragleap import ocr as _ocr
from ragleap import transcription as _transcription
from ragleap import video as _video
from ragleap.transcription import TranscriptionConfig
from ragleap import schema as _schema

logger = logging.getLogger(__name__)

__version__ = "0.5.8"
__all__ = ["RagLeap", "ProviderConfig", "EmbeddingConfig", "IngestResult", "TranscriptionConfig"]


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
        cache_backend: str = "memory",
        redis_url: Optional[str] = None,
        cache_ttl_seconds: int = 86400,
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
        if not cache_enabled:
            self._query_cache = None
        elif cache_backend == "redis":
            if not redis_url:
                raise ValueError("cache_backend='redis' requires redis_url= to be set.")
            self._query_cache = RedisQueryEmbeddingCache(redis_url, max_size=cache_max_size, ttl_seconds=cache_ttl_seconds)
        elif cache_backend == "memory":
            self._query_cache = QueryEmbeddingCache(max_size=cache_max_size)
        else:
            raise ValueError(f"Unknown cache_backend '{cache_backend}'. Use 'memory' or 'redis'.")
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

    def ingest_url(self, url: str, metadata: Optional[Dict] = None) -> IngestResult:
        """
        Fetch a web page, extract clean readable text (stripping nav/
        ads/footers via trafilatura), and ingest it. Requires the
        'web' extra: pip install ragleap-rag[web]. The URL itself is
        used as the stored filename/document_name.
        """
        text = _web.fetch_url_text(url)
        if text is None:
            raise ValueError(f"Could not extract usable text from URL: {url}")
        return self.ingest_text(url, text, metadata=metadata)

    def ingest_image(
        self,
        filename: str,
        raw_bytes: bytes,
        mode: str = "ocr",
        mime_type: str = "image/jpeg",
        metadata: Optional[Dict] = None,
    ) -> IngestResult:
        """
        Ingest an image. Two modes, for two different kinds of images:

        mode="ocr" (default) reads literal text visible in the image
        (scanned documents, screenshots, photos of text). Requires the
        'ocr' extra AND the Tesseract binary installed on the system.

        mode="caption" describes the image's contents using a vision-
        capable model instead - for photos, diagrams, or charts with
        no readable text. Currently requires Gemini configured as the
        primary or a fallback provider.
        """
        if mode == "ocr":
            text = _ocr.extract_text_from_image(raw_bytes)
        elif mode == "caption":
            text = self._generator.describe_image(raw_bytes, mime_type=mime_type)
        else:
            raise ValueError(f"Unknown mode '{mode}'. Use 'ocr' or 'caption'.")

        return self.ingest_text(filename, text, metadata=metadata)

    def ingest_audio(
        self,
        filename: str,
        raw_bytes: bytes,
        transcriber: Optional["TranscriptionConfig"] = None,
        metadata: Optional[Dict] = None,
    ) -> IngestResult:
        """
        Transcribe audio to text and ingest it. Pass a TranscriptionConfig
        to choose the provider (whisper or deepgram) and options; if
        omitted, defaults to OpenAI's hosted Whisper API using
        OPENAI_API_KEY from the environment.

        Whisper is a strong general-purpose baseline but has real
        limitations: accuracy varies by language, there is no built-in
        denoising (quiet/noisy audio genuinely degrades transcription
        quality), and no domain-vocabulary biasing by default (brand
        names and jargon commonly get mangled unless you pass a
        prompt hint via TranscriptionConfig). Use provider='deepgram'
        if these matter for your use case.
        """
        config = transcriber or _transcription.TranscriptionConfig(provider="whisper")
        service = _transcription.TranscriptionService(config)
        text = service.transcribe(filename, raw_bytes)
        return self.ingest_text(filename, text, metadata=metadata)

    def ingest_video(
        self,
        filename: str,
        raw_bytes: bytes,
        transcriber: Optional["TranscriptionConfig"] = None,
        metadata: Optional[Dict] = None,
    ) -> IngestResult:
        """
        Extract the audio track from a video file (requires the
        ffmpeg binary installed on the system - not pip-installable),
        transcribe it, and ingest the result. This is audio ingestion
        plus an extraction step - no separate video-specific
        transcription logic. Same transcriber= options and the same
        honest limitations as ingest_audio() apply (see its docstring).

        If the video already has a matching subtitle file (.vtt/.srt),
        ingesting that directly via ingest() is cheaper and more
        accurate than re-transcribing the audio.
        """
        audio_bytes = _video.extract_audio_from_video(raw_bytes, filename)
        return self.ingest_audio(filename, audio_bytes, transcriber=transcriber, metadata=metadata)

    def ingest_text(
        self,
        filename: str,
        text: str,
        metadata: Optional[Dict] = None,
        sanitize: bool = True,
        warn_on_injection_risk: bool = True,
    ) -> IngestResult:
        """
        Same as ingest(), but for text you've already extracted yourself.

        sanitize=True (default) strips null bytes, control characters,
        and invisible/zero-width Unicode from the text before chunking.
        warn_on_injection_risk=True (default) logs a warning if common
        prompt-injection trigger phrases are found - this is a heuristic
        signal for review, not a guarantee the content is safe, and
        nothing is blocked automatically.
        """
        if sanitize:
            text = _sanitization.sanitize_text(text)

        if warn_on_injection_risk:
            risk_matches = _sanitization.detect_injection_risk(text)
            if risk_matches:
                logger.warning(
                    f"Possible prompt-injection content in '{filename}': "
                    f"matched phrase(s) {risk_matches}. This is a heuristic "
                    f"signal, not a block - review the content if unexpected."
                )

        chunks = self._chunker.chunk_text(text)
        if not chunks:
            raise ValueError("No chunks produced from input text — is it empty?")

        document_id = str(uuid.uuid4())
        with self._pool.get_connection() as conn:
          try:
            cur = conn.cursor()
            import json as _json
            cur.execute(
                "INSERT INTO documents (id, filename, metadata) VALUES (%s, %s, %s::jsonb)",
                (document_id, filename, _json.dumps(metadata or {})),
            )

            stored = 0
            for chunk in chunks:
                embedding = self._embedder.embed_text(chunk["text"])
                if embedding is None:
                    logger.warning(f"Skipping chunk {chunk['chunk_index']} — embedding failed")
                    continue

                embedding_literal = "[" + ",".join(str(float(x)) for x in embedding) + "]"
                cur.execute(
                    """
                    INSERT INTO chunks (document_id, document_name, chunk_index, text, token_count, embedding, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s::vector, %s::jsonb)
                    """,
                    (document_id, filename, chunk["chunk_index"], chunk["text"], chunk["token_count"], embedding_literal, _json.dumps(metadata or {})),
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
        metadata_filter: Optional[Dict] = None,
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
                    "sources": [], "citations": [], "provider_used": None, "usage": None, "chunks_sent": 0}

        pool_size = top_k * 4 if rerank else top_k
        if hybrid:
            chunks = self._retriever.search_hybrid_chunks(query, query_embedding, top_k=pool_size, metadata_filter=metadata_filter)
        else:
            chunks = self._retriever.search_similar_chunks(query_embedding, top_k=pool_size, metadata_filter=metadata_filter)

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
        rerank: bool = False,
        metadata_filter: Optional[Dict] = None,
    ) -> Iterator[str]:
        """Same as ask(), but yields the answer incrementally as it's
        generated. If session_id is set, the full assembled answer is
        stored to memory once streaming completes."""
        query_embedding = self._embed_query_cached(query)
        if query_embedding is None:
            yield "Sorry, I couldn't process your question (embedding failed)."
            return

        pool_size = top_k * 4 if rerank else top_k
        if hybrid:
            chunks = self._retriever.search_hybrid_chunks(query, query_embedding, top_k=pool_size, metadata_filter=metadata_filter)
        else:
            chunks = self._retriever.search_similar_chunks(query_embedding, top_k=pool_size, metadata_filter=metadata_filter)

        if rerank and chunks:
            if self._reranker is None:
                self._reranker = RerankerService()
            chunks = self._reranker.rerank(query, chunks, top_k=top_k)

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

    def list_documents(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        List previously ingested documents, most recently uploaded first.
        Returns: [{"document_id": str, "filename": str, "uploaded_at": ...,
                   "chunk_count": int}, ...]
        """
        with self._pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT d.id, d.filename, d.uploaded_at, d.metadata, COUNT(c.id) AS chunk_count
                FROM documents d
                LEFT JOIN chunks c ON c.document_id = d.id
                GROUP BY d.id, d.filename, d.uploaded_at, d.metadata
                ORDER BY d.uploaded_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
            cur.close()

        return [
            {"document_id": str(r[0]), "filename": r[1], "uploaded_at": r[2], "metadata": r[3], "chunk_count": r[4]}
            for r in rows
        ]

    def delete_document(self, document_id: str) -> bool:
        """
        Delete a document and all its chunks (cascades automatically via
        the chunks.document_id foreign key). Returns True if a document
        was actually deleted, False if document_id did not exist.
        """
        with self._pool.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            cur.close()

        if deleted:
            logger.info(f"Deleted document {document_id}")
        else:
            logger.warning(f"delete_document: no document found with id {document_id}")
        return deleted

    def update_document(self, document_id: str, text: str, filename: Optional[str] = None) -> IngestResult:
        """
        Replace a document's content. This is implemented as delete +
        re-ingest under the hood, not an in-place edit - chunk boundaries
        and embeddings for the old content are not preserved, and the
        document gets a new document_id. Use filename= to also rename it;
        omit to keep the existing filename.
        """
        existing_filename = filename
        if existing_filename is None:
            with self._pool.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT filename FROM documents WHERE id = %s", (document_id,))
                row = cur.fetchone()
                cur.close()
            if row is None:
                raise ValueError(f"No document found with id {document_id}")
            existing_filename = row[0]

        self.delete_document(document_id)
        return self.ingest_text(existing_filename, text)

    async def aingest(self, filename: str, raw_bytes: bytes) -> IngestResult:
        """
        Async version of ingest(). Runs the existing sync implementation
        in a worker thread, so it does not block the event loop - the
        underlying DB/embedding calls are not natively async, but a
        blocking call to psycopg2 or an HTTP embedding API would
        otherwise stall an async web server (FastAPI, etc.) on every
        request.
        """
        import asyncio
        return await asyncio.to_thread(self.ingest, filename, raw_bytes)

    async def aingest_text(self, filename: str, text: str) -> IngestResult:
        """Async version of ingest_text(). See aingest() for details."""
        import asyncio
        return await asyncio.to_thread(self.ingest_text, filename, text)

    async def aingest_url(self, url: str, metadata: Optional[Dict] = None) -> IngestResult:
        """Async version of ingest_url(). See aingest() for details."""
        import asyncio
        return await asyncio.to_thread(self.ingest_url, url, metadata)

    async def aingest_image(
        self,
        filename: str,
        raw_bytes: bytes,
        mode: str = "ocr",
        mime_type: str = "image/jpeg",
        metadata: Optional[Dict] = None,
    ) -> IngestResult:
        """Async version of ingest_image(). See aingest() for details."""
        import asyncio
        return await asyncio.to_thread(self.ingest_image, filename, raw_bytes, mode, mime_type, metadata)

    async def aingest_audio(
        self,
        filename: str,
        raw_bytes: bytes,
        transcriber: Optional["TranscriptionConfig"] = None,
        metadata: Optional[Dict] = None,
    ) -> IngestResult:
        """Async version of ingest_audio(). See aingest() for details."""
        import asyncio
        return await asyncio.to_thread(self.ingest_audio, filename, raw_bytes, transcriber, metadata)

    async def aingest_video(
        self,
        filename: str,
        raw_bytes: bytes,
        transcriber: Optional["TranscriptionConfig"] = None,
        metadata: Optional[Dict] = None,
    ) -> IngestResult:
        """Async version of ingest_video(). See aingest() for details."""
        import asyncio
        return await asyncio.to_thread(self.ingest_video, filename, raw_bytes, transcriber, metadata)

    async def ingest_batch(self, items: List[Dict]) -> List[Dict]:
        """
        Ingest a mixed batch of documents concurrently - any
        combination of types, e.g. a PDF, a video, an image, and a
        URL all in one call. Each item runs independently: one
        item's failure does not stop or roll back the others, and
        each successfully ingested item is committed on its own (the
        same as calling each ingest_*() method separately, just
        concurrent instead of sequential).

        items: list of dicts, each with:
          - "type": one of "file", "url", "image", "audio", "video"
            ("file" covers ingest()'s full format range - pdf, docx,
            xlsx, etc. - dispatched by filename extension)
          - "filename": required for file/image/audio/video
          - "raw_bytes": required for file/image/audio/video
          - "url": required for type="url"
          - "mode": optional, image only ("ocr" or "caption")
          - "transcriber": optional, audio/video only (TranscriptionConfig)
          - "metadata": optional, any type

        Returns a list of dicts, one per input item, in the same
        order: {"success": bool, "result": IngestResult | None,
                "error": str | None}. Check "success" per item rather
        than assuming the whole batch succeeded - a batch of 10 with
        3 failures still stores the other 7.
        """
        async def _run_one(item: Dict) -> Dict:
            try:
                item_type = item.get("type")
                metadata = item.get("metadata")

                if item_type == "file":
                    result = await self.aingest(item["filename"], item["raw_bytes"])
                elif item_type == "url":
                    result = await self.aingest_url(item["url"], metadata=metadata)
                elif item_type == "image":
                    result = await self.aingest_image(
                        item["filename"], item["raw_bytes"],
                        mode=item.get("mode", "ocr"),
                        mime_type=item.get("mime_type", "image/jpeg"),
                        metadata=metadata,
                    )
                elif item_type == "audio":
                    result = await self.aingest_audio(
                        item["filename"], item["raw_bytes"],
                        transcriber=item.get("transcriber"), metadata=metadata,
                    )
                elif item_type == "video":
                    result = await self.aingest_video(
                        item["filename"], item["raw_bytes"],
                        transcriber=item.get("transcriber"), metadata=metadata,
                    )
                else:
                    raise ValueError(f"Unknown batch item type '{item_type}'. Use file, url, image, audio, or video.")

                return {"success": True, "result": result, "error": None}
            except Exception as e:
                logger.warning(f"ingest_batch item failed (type={item.get('type')}, filename={item.get('filename') or item.get('url')}): {e}")
                return {"success": False, "result": None, "error": str(e)}

        import asyncio
        return await asyncio.gather(*[_run_one(item) for item in items])

    async def aask(
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
        """Async version of ask(). See aingest() for details on the
        threading approach."""
        import asyncio
        return await asyncio.to_thread(
            self.ask, query, top_k=top_k, temperature=temperature,
            system_prompt=system_prompt, max_tokens=max_tokens, hybrid=hybrid,
            session_id=session_id, rerank=rerank,
        )

    async def aask_stream(
        self,
        query: str,
        top_k: int = 5,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        hybrid: bool = True,
        session_id: Optional[str] = None,
        rerank: bool = False,
        metadata_filter: Optional[Dict] = None,
    ):
        """
        Async version of ask_stream(). Runs the sync generator in a
        worker thread and re-yields pieces as they become available,
        so the event loop is not blocked while waiting on each chunk.
        """
        import asyncio
        import queue

        q: queue.Queue = queue.Queue()
        SENTINEL = object()

        def _run():
            try:
                for piece in self.ask_stream(
                    query, top_k=top_k, temperature=temperature,
                    system_prompt=system_prompt, max_tokens=max_tokens,
                    hybrid=hybrid, session_id=session_id,
                    rerank=rerank, metadata_filter=metadata_filter,
                ):
                    q.put(piece)
            finally:
                q.put(SENTINEL)

        task = asyncio.create_task(asyncio.to_thread(_run))
        try:
            while True:
                piece = await asyncio.to_thread(q.get)
                if piece is SENTINEL:
                    break
                yield piece
        finally:
            await task
