"""
ragleap_tools.base

Core Tool/ToolResult abstraction every tool implementation in this
package uses. Deliberately minimal - a name, a description, a JSON
Schema for parameters (the OpenAI/Gemini function-calling convention,
so no adapter layer is needed for either provider), and a handler
callable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class ToolResult:
    """Result of calling a tool's handler.

    success=False + error=<message> on any failure - handlers should
    never raise for expected failure modes (bad input, file not found,
    etc.); they should catch and return a ToolResult so a caller's
    tool-calling loop can feed a clean error back to the LLM instead of
    crashing. Handlers MAY still raise for genuinely unexpected
    programming errors - that's a real bug, not user input to explain
    to the model.
    """

    success: bool
    result: Any = None
    error: Optional[str] = None


@dataclass
class Tool:
    """A single callable tool with an OpenAI/Gemini-compatible schema.

    parameters: a JSON Schema object (the same shape both OpenAI's
    `tools=[{"type": "function", "function": {...}}]` and Gemini's
    `FunctionDeclaration` expect for their own `parameters` field) -
    e.g. {"type": "object", "properties": {...}, "required": [...]}.

    handler: called with the tool call's arguments as keyword
    arguments (already parsed from whatever JSON the model returned -
    parsing that JSON is the caller's responsibility, not this
    package's). Must return a ToolResult, never raise for expected
    failure modes (see ToolResult's docstring).
    """

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., ToolResult]

    def to_openai_schema(self) -> Dict[str, Any]:
        """Returns the {"type": "function", "function": {...}} shape
        OpenAI's `tools=` parameter expects."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_gemini_schema(self) -> Dict[str, Any]:
        """Returns the shape google-genai's FunctionDeclaration expects
        (name/description/parameters, same JSON Schema convention)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def call(self, **kwargs: Any) -> ToolResult:
        """Invokes the handler with the given keyword arguments."""
        return self.handler(**kwargs)
