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

## Document ingestion and search (optional, needs ragleap-rag)

```bash
pip install ragleap-tools[ingest]
```

```python
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap_tools import IngestConfig, make_ingest_tool, SearchConfig, make_search_tool

rag = RagLeap(database_url="...", primary=ProviderConfig(...), embedder=EmbeddingConfig(...))
ingest_tool = make_ingest_tool(IngestConfig(rag=rag))
search_tool = make_search_tool(SearchConfig(rag=rag))
```

`ingest_document` wraps `ragleap-rag`'s already-tested `ingest_text()` -
no new ingestion logic, just a tool schema on top of the real
28-format-capable pipeline. As of v0.1.1, it stores the filename as
metadata (`{"filename": filename}`), enabling the per-document search
below - v0.1.0 did not pass any metadata, which silently made
per-document filtering impossible.

`search_documents` wraps `ragleap-rag`'s already-tested `retrieve()`
for hybrid vector+keyword search over previously ingested documents.
Chunk dicts are returned unmodified - this tool doesn't assume
`ragleap-rag`'s exact field set. Pass an optional `filename=` to scope
the search to a single document previously ingested via
`ingest_document`:

```python
result = search_tool.call(query="what was the Q3 revenue?", filename="q3-report.pdf")
```

`ragleap-rag` owns the actual ingestion and retrieval logic; these are
thin adapters, same pattern `ragleap-graph` uses for its own optional
`ragleap-rag` dependency.

## Web search (BYOK, no extra dependencies)

```python
from ragleap_tools import WebSearchConfig, TavilySearchProvider, make_web_search_tool

provider = TavilySearchProvider(api_key="...")  # or SerperSearchProvider(api_key="...")
search_tool = make_web_search_tool(WebSearchConfig(provider=provider))

result = search_tool.call(query="latest pgvector release", num_results=5)
# result.result == {"results": [{"title": ..., "url": ..., "snippet": ...}, ...], "count": 5}
```

Bring your own key: you construct the provider you want with your own
`api_key`. There is no default provider and no environment-variable
fallback. Uses only the standard library (`urllib.request`), so
`ragleap-tools` still has zero required dependencies. `SearchProvider`
is a small abstract class - implement `search(query, num_results)` to
plug in any other search engine.

`num_results` is chosen by the model and costs your API quota, so it is
clamped to 1-20.

Honest limitations: request shapes for both reference providers were
checked against their current public docs, but **neither has been
called against a live account** - treat them as best-effort until
confirmed by someone with a real key. Results are text from arbitrary
third-party pages, so treat them as untrusted input: this tool does not
screen them for prompt injection. There is no caching, rate limiting
or deduplication.

## GitHub repository search (BYOK-optional, no extra dependencies)

```python
from ragleap_tools import GitHubSearchConfig, make_github_search_tool

tool = make_github_search_tool(GitHubSearchConfig())  # token optional
# or: GitHubSearchConfig(token="...") for a higher rate limit

result = tool.call(query="language:python topic:llm", num_results=5, sort="stars")
# result.result == {"results": [{"full_name": ..., "url": ..., "description": ..., "stars": ..., "language": ...}, ...], "count": 5}
```

Works without a token, at GitHub's real unauthenticated rate limit (60
requests/hour per IP) - pass `token=` for a higher limit. No
environment-variable fallback: if you want a token used, you pass it.
Supports GitHub's real search qualifiers in the query string
(`language:`, `stars:`, `topic:`, etc.), same as GitHub's own search UI.
Scoped to repository search only, not code or issue search. Standard
library only (`urllib.request`) - no new dependency.

## Deliberately out of scope

Each of these needs its own security-focused design pass, not a
rushed inclusion here:

- **Code execution** - a real sandboxing/resource-limit design
  decision, not something to bolt on alongside a calculator.
- **HTTP fetch** - letting an LLM request arbitrary URLs carries real
  SSRF risk, same care level as code execution.
- **Database/business-system connectors** (SQL, CRM, payment
  processors, etc.) - some of what this ecosystem already has
  elsewhere (e.g. a live payment processor) would be a materially
  different risk if exposed to LLM tool-calling without deliberate
  guardrails (dry-run modes, confirmation steps, scoped permissions).

## Status

v0.3.0. 100 tests, all passing, including real security verification
for the two risk-sensitive tools (calculator's code-injection
rejection, file ops' path-traversal and symlink-escape rejection) -
not just documented as safe, actually tested against real attack
vectors.

## License

MIT
