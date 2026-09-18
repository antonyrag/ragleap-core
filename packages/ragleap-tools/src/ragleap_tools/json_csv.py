"""
ragleap_tools.json_csv

Parse/query structured data (JSON, CSV) already provided as text - no
filesystem or network access. Uses only json (stdlib, safe) and csv
(stdlib, safe) - no pickle, no eval, no arbitrary deserialization.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from ragleap_tools.base import Tool, ToolResult

MAX_INPUT_CHARS = 500_000


def parse_json(text: str) -> ToolResult:
    if len(text) > MAX_INPUT_CHARS:
        return ToolResult(success=False, error=f"Input too large (max {MAX_INPUT_CHARS} chars)")
    try:
        return ToolResult(success=True, result=json.loads(text))
    except json.JSONDecodeError as e:
        return ToolResult(success=False, error=f"Invalid JSON: {e}")


def parse_csv(text: str, has_header: bool = True) -> ToolResult:
    if len(text) > MAX_INPUT_CHARS:
        return ToolResult(success=False, error=f"Input too large (max {MAX_INPUT_CHARS} chars)")
    try:
        reader = csv.DictReader(io.StringIO(text)) if has_header else csv.reader(io.StringIO(text))
        rows = list(reader)
        return ToolResult(success=True, result=rows)
    except csv.Error as e:
        return ToolResult(success=False, error=f"Invalid CSV: {e}")


PARSE_JSON_TOOL = Tool(
    name="parse_json",
    description="Parse a JSON string into structured data.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "The JSON text to parse."}},
        "required": ["text"],
    },
    handler=parse_json,
)

PARSE_CSV_TOOL = Tool(
    name="parse_csv",
    description="Parse CSV text into a list of rows (dicts if has_header=True, lists otherwise).",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The CSV text to parse."},
            "has_header": {"type": "boolean", "description": "Whether the first row is a header. Defaults to true."},
        },
        "required": ["text"],
    },
    handler=parse_csv,
)
