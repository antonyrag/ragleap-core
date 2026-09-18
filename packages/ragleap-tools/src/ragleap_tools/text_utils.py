"""
ragleap_tools.text_utils

Basic text transformation/extraction. Uses Python's re module with a
fixed, small set of caller-provided patterns - re.search()/findall()
with a length-limited pattern and a length-limited input string, to
avoid pathological catastrophic-backtracking regex DoS from being a
realistic concern given the size limits enforced.
"""

from __future__ import annotations

import re
from typing import List

from ragleap_tools.base import Tool, ToolResult

MAX_TEXT_CHARS = 200_000
MAX_PATTERN_CHARS = 500


def regex_extract(text: str, pattern: str) -> ToolResult:
    if len(text) > MAX_TEXT_CHARS:
        return ToolResult(success=False, error=f"Text too large (max {MAX_TEXT_CHARS} chars)")
    if len(pattern) > MAX_PATTERN_CHARS:
        return ToolResult(success=False, error=f"Pattern too large (max {MAX_PATTERN_CHARS} chars)")
    try:
        matches = re.findall(pattern, text)
        return ToolResult(success=True, result=matches)
    except re.error as e:
        return ToolResult(success=False, error=f"Invalid regex: {e}")


def word_count(text: str) -> ToolResult:
    if len(text) > MAX_TEXT_CHARS:
        return ToolResult(success=False, error=f"Text too large (max {MAX_TEXT_CHARS} chars)")
    words = text.split()
    return ToolResult(success=True, result={"words": len(words), "characters": len(text), "lines": text.count("\n") + 1})


def text_case_transform(text: str, mode: str) -> ToolResult:
    if len(text) > MAX_TEXT_CHARS:
        return ToolResult(success=False, error=f"Text too large (max {MAX_TEXT_CHARS} chars)")
    transforms = {
        "upper": str.upper,
        "lower": str.lower,
        "title": str.title,
        "capitalize": str.capitalize,
    }
    if mode not in transforms:
        return ToolResult(success=False, error=f"Unknown mode. Supported: {sorted(transforms)}")
    return ToolResult(success=True, result=transforms[mode](text))


REGEX_EXTRACT_TOOL = Tool(
    name="regex_extract",
    description="Extract all matches of a regex pattern from text.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "pattern": {"type": "string", "description": "A Python regex pattern."},
        },
        "required": ["text", "pattern"],
    },
    handler=regex_extract,
)

WORD_COUNT_TOOL = Tool(
    name="word_count",
    description="Count words, characters, and lines in text.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    handler=word_count,
)

TEXT_CASE_TRANSFORM_TOOL = Tool(
    name="text_case_transform",
    description="Transform text case: upper, lower, title, or capitalize.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "mode": {"type": "string", "enum": ["upper", "lower", "title", "capitalize"]},
        },
        "required": ["text", "mode"],
    },
    handler=text_case_transform,
)
