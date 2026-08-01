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

try:
    from ragleap.vectorstores.weaviate_backend import WeaviateBackend
    __all__.append("WeaviateBackend")
except ImportError:
    pass  # weaviate extra not installed - WeaviateBackend simply unavailable, not an error

try:
    from ragleap.vectorstores.qdrant_backend import QdrantBackend
    __all__.append("QdrantBackend")
except ImportError:
    pass  # qdrant extra not installed - QdrantBackend simply unavailable, not an error

try:
    from ragleap.vectorstores.milvus_backend import MilvusBackend
    __all__.append("MilvusBackend")
except ImportError:
    pass  # milvus extra not installed - MilvusBackend simply unavailable, not an error
