"""
ragleap_tools.ingest

Wraps ragleap-rag's already-tested ingest_text() as a tool - no new
ingestion logic, just a schema on top of the real 28-format-capable
pipeline. ragleap-rag is an optional dependency, same pattern as
ragleap_graph.extraction's optional GenerationService import: users
who only need the other 6 tools (calculator, file ops, etc.) don't
need ragleap-rag installed at all.

v0.1.1: now passes metadata={"filename": filename} to ingest_text() -
previously passed no metadata at all, which silently made every
document ingested through this tool unfilterable by
ragleap_tools.search's filename= parameter (metadata_filter matches
against the metadata dict, not the document_id/document_name
columns). Backward compatible: existing callers get a new capability,
nothing about the tool's signature or return shape changed.
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
class IngestConfig:
    """rag: an already-constructed, already-configured RagLeap
    instance (its own database_url/provider/embedder setup is the
    caller's responsibility - this tool does not own that lifecycle,
    same as ragleap_graph.retrieval.GraphRetriever not owning its
    GraphIndex/RagLeap instances)."""
    rag: Any  # type: RagLeap, left as Any so this module still imports
    # cleanly with ragleap-rag absent - only the handler at call time
    # actually needs a real RagLeap instance.


def ingest_document(config: IngestConfig, filename: str, text: str) -> ToolResult:
    if RagLeap is None:
        return ToolResult(
            success=False,
            error="ragleap-rag is not installed. Install it with: pip install ragleap-tools[ingest]",
        )
    try:
        result = config.rag.ingest_text(filename, text, metadata={"filename": filename})
        return ToolResult(
            success=True,
            result={"document_id": result.document_id, "chunks_stored": result.chunks_stored},
        )
    except ValueError as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def make_ingest_tool(config: IngestConfig) -> Tool:
    """Returns a single ingest_document Tool bound to this config's
    RagLeap instance via closure, same binding pattern as
    file_ops.make_file_tools()."""
    return Tool(
        name="ingest_document",
        description=(
            "Ingest a piece of text as a new document into the RAG index "
            "(chunks, embeds, and stores it for later retrieval). Supports "
            "any of ragleap-rag's 28 real ingestion formats if the text was "
            "already extracted from one of those formats by the caller. "
            "Stores the filename as metadata, so search_documents' filename= "
            "parameter can later scope retrieval to just this document."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "A name/label for this document."},
                "text": {"type": "string", "description": "The text content to ingest."},
            },
            "required": ["filename", "text"],
        },
        handler=lambda filename, text: ingest_document(config, filename, text),
    )
