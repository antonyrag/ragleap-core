"""
ragleap-vectorstores: pluggable vector backends beyond ragleap-rag core's 6.

Scaffold only - no backends implemented yet. Backends will be added here
following ragleap-rag's own vectorstores/__init__.py pattern: each backend
import wrapped in try/except ImportError, so a missing optional extra
simply makes that one backend unavailable rather than breaking the package.
"""

__all__ = []
