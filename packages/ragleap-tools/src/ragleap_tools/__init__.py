"""
ragleap_tools - standalone, dependency-light tool implementations for
LLM tool-calling. Exposes OpenAI/Gemini-style function-calling schemas.

Deliberately does NOT own a tool-calling execution loop - that's
ragleap-agents' job (per the project roadmap's own split). This package
is just the tools: name, description, JSON Schema parameters, and a
safe handler function you invoke yourself once your LLM picks a tool.

v0.1.0 - 7 tools:
  calculator, file ops (read/write/list), get_current_datetime,
  add_to_date, date_difference, convert_length, convert_weight,
  convert_temperature, parse_json, parse_csv, regex_extract,
  word_count, text_case_transform, ingest_document (needs the
  optional ragleap-rag dependency: pip install ragleap-tools[ingest])

Deliberately out of scope for now (each needs its own security-focused
design pass, not a rushed inclusion here): code execution, web search,
HTTP fetch, and database/business-system connectors (SQL, CRM,
payment processors, etc.) - the last of those specifically because
some of the connectors this ecosystem already has elsewhere (e.g. a
live payment processor) would be a materially different risk if
exposed to LLM tool-calling without deliberate guardrails.
"""

from ragleap_tools.base import Tool, ToolResult
from ragleap_tools.calculator import CALCULATOR_TOOL
from ragleap_tools.datetime_tools import ADD_TO_DATE_TOOL, CURRENT_DATETIME_TOOL, DATE_DIFFERENCE_TOOL
from ragleap_tools.file_ops import FileOpsConfig, make_file_tools
from ragleap_tools.ingest import IngestConfig, make_ingest_tool
from ragleap_tools.json_csv import PARSE_CSV_TOOL, PARSE_JSON_TOOL
from ragleap_tools.text_utils import REGEX_EXTRACT_TOOL, TEXT_CASE_TRANSFORM_TOOL, WORD_COUNT_TOOL
from ragleap_tools.unit_conversion import CONVERT_LENGTH_TOOL, CONVERT_TEMPERATURE_TOOL, CONVERT_WEIGHT_TOOL

__version__ = "0.1.0"

# Tools with no config/state needed - usable directly.
STATELESS_TOOLS = [
    CALCULATOR_TOOL,
    CURRENT_DATETIME_TOOL,
    ADD_TO_DATE_TOOL,
    DATE_DIFFERENCE_TOOL,
    CONVERT_LENGTH_TOOL,
    CONVERT_WEIGHT_TOOL,
    CONVERT_TEMPERATURE_TOOL,
    PARSE_JSON_TOOL,
    PARSE_CSV_TOOL,
    REGEX_EXTRACT_TOOL,
    WORD_COUNT_TOOL,
    TEXT_CASE_TRANSFORM_TOOL,
]

__all__ = [
    "Tool",
    "ToolResult",
    "STATELESS_TOOLS",
    "CALCULATOR_TOOL",
    "CURRENT_DATETIME_TOOL",
    "ADD_TO_DATE_TOOL",
    "DATE_DIFFERENCE_TOOL",
    "CONVERT_LENGTH_TOOL",
    "CONVERT_WEIGHT_TOOL",
    "CONVERT_TEMPERATURE_TOOL",
    "PARSE_JSON_TOOL",
    "PARSE_CSV_TOOL",
    "REGEX_EXTRACT_TOOL",
    "WORD_COUNT_TOOL",
    "TEXT_CASE_TRANSFORM_TOOL",
    "FileOpsConfig",
    "make_file_tools",
    "IngestConfig",
    "make_ingest_tool",
    "__version__",
]
