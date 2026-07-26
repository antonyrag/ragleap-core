from ragleap.vectorstores.base import VectorBackend
from ragleap.vectorstores.pgvector import PgVectorBackend

__all__ = ["VectorBackend", "PgVectorBackend"]

try:
    from ragleap.vectorstores.faiss_backend import FAISSBackend
    __all__.append("FAISSBackend")
except ImportError:
    pass  # faiss extra not installed - FAISSBackend simply unavailable, not an error
