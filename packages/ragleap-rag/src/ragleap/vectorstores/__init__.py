from ragleap.vectorstores.base import VectorBackend
from ragleap.vectorstores.pgvector import PgVectorBackend

__all__ = ["VectorBackend", "PgVectorBackend"]

try:
    from ragleap.vectorstores.faiss_backend import FAISSBackend
    __all__.append("FAISSBackend")
except ImportError:
    pass  # faiss extra not installed - FAISSBackend simply unavailable, not an error

try:
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    __all__.append("PineconeBackend")
except ImportError:
    pass  # pinecone extra not installed - PineconeBackend simply unavailable, not an error
