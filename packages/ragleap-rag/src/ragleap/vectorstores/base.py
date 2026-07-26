"""
Abstract vector storage backend for ragleap-rag.

RagLeap defaults to PgVectorBackend (Postgres + pgvector) for full
backward compatibility. Other backends (FAISS, Pinecone, ...) can be
swapped in via the vector_backend= constructor parameter. Backends
differ in what they can do - supports_sparse() is a real capability
flag, not a formality: callers (RagLeap.ask) check it before assuming
hybrid search is meaningful for a given backend.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class VectorBackend(ABC):
    """Every vector storage backend must implement this interface."""

    @abstractmethod
    def init_schema(self, dimensions: int) -> None:
        """Create/verify whatever storage structure this backend needs. Idempotent."""

    @abstractmethod
    def insert_document(self, document_id: str, filename: str, metadata: Dict) -> None:
        """Register a new document (parent record for its chunks)."""

    @abstractmethod
    def insert_chunk(
        self, document_id: str, document_name: str, chunk_index: int,
        text: str, token_count: int, embedding: List[float], metadata: Dict,
    ) -> None:
        """Store one chunk with its embedding."""

    @abstractmethod
    def search_dense(self, embedding: List[float], top_k: int, metadata_filter: Optional[Dict] = None) -> List[Dict]:
        """Vector similarity search. Must return dicts with at least:
        chunk_id, text, similarity_score, document_id, document_name, chunk_index."""

    def search_sparse(self, query_text: str, top_k: int, metadata_filter: Optional[Dict] = None) -> List[Dict]:
        """Keyword/full-text search. Default: not supported (see supports_sparse())."""
        return []

    def search_hybrid(self, query_text: str, embedding: List[float], top_k: int, metadata_filter: Optional[Dict] = None) -> List[Dict]:
        """Combined dense+sparse via RRF. Default: falls back to dense-only
        if this backend doesn't support sparse search - see supports_sparse()."""
        return self.search_dense(embedding, top_k, metadata_filter)

    def supports_sparse(self) -> bool:
        """Whether this backend can do real keyword/full-text search.
        Callers should check this rather than assume hybrid search is
        doing anything beyond dense search under the hood."""
        return False

    @abstractmethod
    def list_documents(self, limit: int, offset: int) -> List[Dict]:
        """List documents, most recent first."""

    @abstractmethod
    def delete_document(self, document_id: str) -> bool:
        """Delete a document and its chunks. Returns True if something was deleted."""

    @abstractmethod
    def get_document_filename(self, document_id: str) -> Optional[str]:
        """Return a document's stored filename, or None if it doesn't exist.
        Used by update_document() when no explicit filename= is given."""

