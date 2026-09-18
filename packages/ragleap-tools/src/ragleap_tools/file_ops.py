"""
ragleap_tools.file_ops

Sandboxed file read/write/list tools. Every operation is confined to a
caller-specified root directory via FileOpsConfig(root_dir=...) -
there is no global/unsandboxed mode. Path resolution uses
Path.resolve() (which follows symlinks) and then checks the resolved
path is actually inside the resolved root, so both ../ traversal AND
symlink-based escapes are rejected, not just naive string prefix
matching (which symlinks would defeat).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ragleap_tools.base import Tool, ToolResult

MAX_READ_BYTES = 1_000_000  # 1MB - a tool result feeding back into an
# LLM context has no business being larger than this; reject rather
# than silently truncate, so the caller knows to read a smaller file.
MAX_WRITE_BYTES = 1_000_000


@dataclass
class FileOpsConfig:
    """root_dir: the ONLY directory tree these tools may touch. No
    caller-supplied absolute path or ../ sequence can escape it -
    enforced in _resolve_safe_path(), not just documented here."""
    root_dir: str


class PathEscapeError(ValueError):
    """Raised when a requested path would resolve outside root_dir -
    whether via ../ traversal or a symlink. Never silently clamped or
    corrected - always rejected outright."""


def _resolve_safe_path(config: FileOpsConfig, relative_path: str) -> Path:
    root = Path(config.root_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"root_dir does not exist or is not a directory: {config.root_dir}")

    # reject absolute paths outright - a caller-supplied "path" must
    # always be interpreted as relative to root, never as a literal
    # filesystem path, or "/etc/passwd" would trivially escape.
    if Path(relative_path).is_absolute():
        raise PathEscapeError(f"Absolute paths are not allowed: {relative_path!r}")

    candidate = (root / relative_path).resolve()

    # is_relative_to() (3.9+) correctly rejects symlink escapes too,
    # since candidate is already the fully-resolved (symlinks
    # followed) real path being checked against the resolved root.
    if not candidate.is_relative_to(root):
        raise PathEscapeError(f"Path escapes root_dir: {relative_path!r}")

    return candidate


def read_file(config: FileOpsConfig, path: str) -> ToolResult:
    try:
        real_path = _resolve_safe_path(config, path)
        if not real_path.exists():
            return ToolResult(success=False, error=f"File not found: {path!r}")
        if not real_path.is_file():
            return ToolResult(success=False, error=f"Not a file: {path!r}")
        size = real_path.stat().st_size
        if size > MAX_READ_BYTES:
            return ToolResult(success=False, error=f"File too large ({size} bytes, max {MAX_READ_BYTES})")
        content = real_path.read_text(encoding="utf-8", errors="replace")
        return ToolResult(success=True, result=content)
    except PathEscapeError as e:
        return ToolResult(success=False, error=str(e))
    except (OSError, UnicodeDecodeError) as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def write_file(config: FileOpsConfig, path: str, content: str) -> ToolResult:
    try:
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return ToolResult(success=False, error=f"Content too large (max {MAX_WRITE_BYTES} bytes)")
        real_path = _resolve_safe_path(config, path)
        real_path.parent.mkdir(parents=True, exist_ok=True)
        real_path.write_text(content, encoding="utf-8")
        return ToolResult(success=True, result=f"Wrote {len(content)} characters to {path!r}")
    except PathEscapeError as e:
        return ToolResult(success=False, error=str(e))
    except OSError as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def list_files(config: FileOpsConfig, path: str = ".") -> ToolResult:
    try:
        real_path = _resolve_safe_path(config, path)
        if not real_path.exists():
            return ToolResult(success=False, error=f"Path not found: {path!r}")
        if not real_path.is_dir():
            return ToolResult(success=False, error=f"Not a directory: {path!r}")
        entries = sorted(
            f"{p.name}/" if p.is_dir() else p.name
            for p in real_path.iterdir()
        )
        return ToolResult(success=True, result=entries)
    except PathEscapeError as e:
        return ToolResult(success=False, error=str(e))
    except OSError as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def make_file_tools(config: FileOpsConfig) -> list[Tool]:
    """Returns the 3 file-op Tools, each bound to this specific
    config/root_dir via closures - so the caller can construct
    independently-sandboxed tool sets for different contexts."""

    return [
        Tool(
            name="read_file",
            description="Read the text content of a file within the sandboxed directory.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the sandboxed root directory."},
                },
                "required": ["path"],
            },
            handler=lambda path: read_file(config, path),
        ),
        Tool(
            name="write_file",
            description="Write text content to a file within the sandboxed directory. Creates parent directories as needed.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the sandboxed root directory."},
                    "content": {"type": "string", "description": "Text content to write."},
                },
                "required": ["path", "content"],
            },
            handler=lambda path, content: write_file(config, path, content),
        ),
        Tool(
            name="list_files",
            description="List files and directories within a directory in the sandboxed root.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the sandboxed root directory. Defaults to the root itself."},
                },
                "required": [],
            },
            handler=lambda path=".": list_files(config, path),
        ),
    ]
