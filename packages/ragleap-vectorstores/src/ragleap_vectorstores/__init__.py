"""
ragleap-vectorstores: pluggable vector backends beyond ragleap-rag core's 6.

Each backend import is wrapped in try/except ImportError, matching
ragleap-rag's own vectorstores/__init__.py pattern - a missing optional
extra simply makes that one backend unavailable rather than breaking
the package.
"""
from ragleap.vectorstores.base import VectorBackend

__all__ = ["VectorBackend"]

try:
    from ragleap_vectorstores.chroma_backend import ChromaBackend
    __all__.append("ChromaBackend")
except ImportError:
    pass  # chroma extra not installed - ChromaBackend simply unavailable, not an error
