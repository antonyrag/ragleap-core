# ragleap-agents

A small agent loop over [`ragleap-tools`](https://pypi.org/project/ragleap-tools/)
`Tool` objects. The model proposes **one action at a time**, sees the result,
and proposes the next, up to a hard step cap. You bring the model as a plain
callable; the library has no provider code and no database.

```bash
pip install ragleap-agents
# or: uv add ragleap-agents
```

## Quickstart

```python
from ragleap_tools import CALCULATOR_TOOL
from ragleap_agents import Agent, Policy, TRUSTED

def my_llm(prompt: str) -> str:
    ...  # call any model, return its text

agent = Agent(
    llm=my_llm,
    tools=[CALCULATOR_TOOL],
    policy=Policy(max_steps=4, tools={"calculator": TRUSTED}),
)
result = agent.run("What is 6 * 7?")
print(result.status, result.answer)   # done, a short summary of what was found
for step in result.steps:             # the transcript: tool, arguments, status, observation
    print(step["tool"], step["arguments"], step["status"])
```

## Approval gates: pause and resume

```python
from ragleap_agents import ToolPolicy

policy = Policy(tools={"write_file": ToolPolicy(taints=False, outbound=True, requires_approval=True)})
agent = Agent(my_llm, tools, policy, store=my_store)

result = agent.run("save the report")
if result.status == "awaiting_approval":
    call = result.pending                 # {"call_id", "tool", "arguments", "forced"}
    # ... show it to a human, then, in this process or another one:
    result = agent.resume(result.run_id, {call["call_id"]: True})   # or False to reject
```

A paused run is a plain JSON dict in a `StateStore` (`save`/`load`). The
in-memory store is included; write your own for a file, Redis or a database.
`resume()` raises `ResumeError` if the run is unknown, not awaiting approval,
or the decision does not match the pending call, so an approval cannot be replayed.

## The safety model

- **Every proposal is checked.** The tool must exist and the arguments must fit
  its JSON Schema (required keys, unknown keys, type and enum only; no `$ref` or `oneOf`).
  Anything else stops the run with `stop_reason="invalid_plan"`; no tool runs.
- **Tool results are untrusted data.** They are capped (1,500 characters each,
  4,000 in the prompt), fenced in `<observation>` tags, and lookalike tags inside
  them are neutralised, case-insensitively.
- **Taint rule.** Declare each tool with a `ToolPolicy`: `taints` (its result is
  external content) and `outbound` (it acts on the outside world). Once a tainting
  tool has run, every later outbound tool needs approval, whatever else is configured.
  The policy can only tighten.
- **Fail closed.** A tool with no declared policy counts as both tainting and outbound.
  Use `TRUSTED` only for tools that neither return external content nor act outside.
- **Limits.** `max_steps` (default 4, hard cap 8), a duplicate-action stop, and a
  deadline checked between calls (a running tool is not interrupted).
- **Failures stay contained.** `run()` does not raise for model or tool failures.
  A tool's exception text is never shown to the model or returned; only its type is.

**What this does not do:** it does not stop prompt injection. It limits what an
injected instruction can do, and only as far as your `ToolPolicy` declarations are
accurate. Tool descriptions are shown to the model too (capped at 300 characters),
so tools from an untrusted source (for example a remote MCP server) can inject
through them. Approval prompts are only as good as the human reading them.

## Status

v0.1.0, alpha. 41 tests with a scripted model on Python 3.10, 3.11 and 3.12 (see
`tests/`); each safety property above has a test that fails if the property is broken.

**Not verified:** any real model (no provider has been run through this loop yet),
long runs, concurrent resumes across processes (your store must make resume atomic),
and equivalence with RagLeap Core's own agent loop, which this mirrors as of core
commit `59fd555` (see `docs/design/agent-loop.md`).

## License

MIT
