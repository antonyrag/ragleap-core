# ragleap-tools

Standalone, dependency-light tool implementations for LLM tool-calling.
Exposes OpenAI/Gemini-style function-calling schemas.

```bash
pip install ragleap-tools
```

## What this is (and isn't)

`ragleap-tools` provides `Tool` objects - a name, a description, a JSON
Schema for parameters, and a safe handler function. It does **not** own
a tool-calling execution loop (deciding when to call a tool, running
it, feeding the result back to the model) - that's `ragleap-agents`'
job, per the project roadmap's own split. Wire these tools into your
own tool-calling code, or into `ragleap-agents` once that ships.

## Quickstart

```python
from ragleap_tools import STATELESS_TOOLS, CALCULATOR_TOOL

# Give these to your LLM provider's tools= parameter:
openai_tools = [t.to_openai_schema() for t in STATELESS_TOOLS]
gemini_tools = [t.to_gemini_schema() for t in STATELESS_TOOLS]

# When the model calls one, invoke the handler yourself:
result = CALCULATOR_TOOL.call(expression="2 + 2 * sqrt(16)")
print(result.success, result.result)  # True 10.0
```

## The 12 stateless tools

No configuration needed - import and use directly.

- `CALCULATOR_TOOL` - safe arithmetic (AST-based whitelist, never `eval()`)
- `CURRENT_DATETIME_TOOL`, `ADD_TO_DATE_TOOL`, `DATE_DIFFERENCE_TOOL` - date/time math
- `CONVERT_LENGTH_TOOL`, `CONVERT_WEIGHT_TOOL`, `CONVERT_TEMPERATURE_TOOL` - unit conversion
- `PARSE_JSON_TOOL`, `PARSE_CSV_TOOL` - structured data parsing
- `REGEX_EXTRACT_TOOL`, `WORD_COUNT_TOOL`, `TEXT_CASE_TRANSFORM_TOOL` - text utilities

## File operations (sandboxed, needs configuration)

```python
from ragleap_tools import FileOpsConfig, make_file_tools

config = FileOpsConfig(root_dir="/path/to/a/safe/directory")
read_tool, write_tool, list_tool = make_file_tools(config)
```

Every operation is confined to `root_dir` - both `../` path traversal
and symlink-based escapes are rejected (verified via real security
tests, not just documented), not just naive string-prefix checking.
There is no unsandboxed mode.

## Document ingestion (optional, needs ragleap-rag)

```bash
pip install ragleap-tools[ingest]
```

```python
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap_tools import IngestConfig, make_ingest_tool

rag = RagLeap(database_url="...", primary=ProviderConfig(...), embedder=EmbeddingConfig(...))
ingest_tool = make_ingest_tool(IngestConfig(rag=rag))
```

Wraps `ragleap-rag`'s already-tested `ingest_text()` - no new ingestion
logic, just a tool schema on top of the real 28-format-capable
pipeline. `ragleap-rag` owns the actual ingestion; this is a thin
adapter, same pattern `ragleap-graph` uses for its own optional
`ragleap-rag` dependency.

## Deliberately out of scope for v0.1.0

Each of these needs its own security-focused design pass, not a
rushed inclusion here:

- **Code execution** - a real sandboxing/resource-limit design
  decision, not something to bolt on alongside a calculator.
- **Web search** - needs a pluggable-provider decision (this
  ecosystem's BYOK philosophy applies here too), not a single
  hardcoded provider.
- **HTTP fetch** - letting an LLM request arbitrary URLs carries real
  SSRF risk, same care level as code execution.
- **Database/business-system connectors** (SQL, CRM, payment
  processors, etc.) - some of what this ecosystem already has
  elsewhere (e.g. a live payment processor) would be a materially
  different risk if exposed to LLM tool-calling without deliberate
  guardrails (dry-run modes, confirmation steps, scoped permissions).

## Status

v0.1.0. 51 tests, all passing, including real security verification
for the two risk-sensitive tools (calculator's code-injection
rejection, file ops' path-traversal and symlink-escape rejection) -
not just documented as safe, actually tested against real attack
vectors.

## License

MIT
