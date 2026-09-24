"""
ragleap_tools.search

Wraps ragleap-rag's already-tested retrieve() as a tool - no new
retrieval logic, just a schema on top of the real hybrid vector+
(optional rerank) pipeline across whichever of ragleap-rag's 6+
vector backends is configured. Same optional-dependency pattern as
ingest.py: ragleap-rag is only needed if this tool is actually used,
users who only need the other tools in this package don't need it
installed at all.

Chunk dicts from retrieve() are returned as-is, not reshaped - this
tool does not know or assume the exact field set ragleap-rag's vector
backends populate, so reshaping them risks silently dropping or
renaming a field a caller depends on. Whatever retrieve() returns is
exactly what this tool returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ragleap_tools.base import Tool, ToolResult

try:
    # ragleap-rag is an optional dependency for this tool only - the
    # other tools in this package need nothing beyond the stdlib.
    from ragleap import RagLeap
except ImportError:  # pragma: no cover - exercised when ragleap-rag absent
    RagLeap = None  # type: ignore[assignment,misc]


@dataclass
class SearchConfig:
    """rag: an already-constructed, already-configured RagLeap
    instance (its own database_url/provider/embedder setup is the
    caller's responsibility - this tool does not own that lifecycle,
    same as IngestConfig)."""
    rag: Any  # type: RagLeap, left as Any so this module still imports
    # cleanly with ragleap-rag absent - only the handler at call time
    # actually needs a real RagLeap instance.


def search_documents(
    config: SearchConfig,
    query: str,
    top_k: int = 5,
    rerank: bool = False,
) -> ToolResult:
    if RagLeap is None:
        return ToolResult(
            success=False,
            error="ragleap-rag is not installed. Install it with: pip install ragleap-tools[ingest]",
        )
    try:
        chunks = config.rag.retrieve(query, top_k=top_k, hybrid=True, rerank=rerank)
        return ToolResult(success=True, result={"chunks": chunks, "count": len(chunks)})
    except Exception as e:
        # retrieve() has no documented raise contract (unlike
        # ingest_text's explicit ValueError), so this catches broadly
        # by design - a tool-calling loop should get a clean
        # ToolResult back, never an uncaught exception from a live
        # vector-backend call it doesn't control.
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def make_search_tool(config: SearchConfig) -> Tool:
    """Returns a single search_documents Tool bound to this config's
    RagLeap instance via closure, same binding pattern as
    ingest.make_ingest_tool() and file_ops.make_file_tools()."""
    return Tool(
        name="search_documents",
        description=(
            "Search previously ingested documents for chunks relevant to a "
            "query, using ragleap-rag's hybrid vector+keyword retrieval "
            "across whichever vector backend is configured. Returns the "
            "top matching chunks, not a generated answer - use this when "
            "you need source passages to reason over yourself rather than "
            "a synthesized response."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "top_k": {
                    "type": "integer",
                    "description": "Number of chunks to return.",
                    "default": 5,
                },
                "rerank": {
                    "type": "boolean",
                    "description": "Apply cross-encoder reranking for higher precision (slower).",
                    "default": False,
                },
            },
            "required": ["query"],
        },
        handler=lambda query, top_k=5, rerank=False: search_documents(
            config, query, top_k=top_k, rerank=rerank
        ),
    )
