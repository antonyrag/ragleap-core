# Changelog

All notable changes to `ragleap-agents` are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-10-09

### Added

- Initial version. `Agent(llm, tools, policy, store, summarize)` runs an
  act-observe loop over `ragleap_tools.Tool` objects: the model proposes one
  JSON action per step, sees the result, and continues, up to `max_steps`
  (default 4, hard cap 8). `llm` is any callable `llm(prompt: str) -> str`.
- Every proposal is checked: the tool must exist and the arguments must fit
  the tool's JSON Schema (required keys, unknown keys, type and enum only).
  An invalid proposal stops the run; no tool runs.
- Tool results are untrusted data: capped, fenced, labelled, and lookalike
  tags inside them are neutralised case-insensitively.
- `ToolPolicy(taints, outbound, requires_approval)` per tool. After a tainting
  tool has run, every later outbound tool needs approval. A tool with no
  declared policy counts as both tainting and outbound.
- Pause and resume: an action that needs approval saves the run and returns
  `status="awaiting_approval"` with the pending call; `resume(run_id,
  {call_id: bool})` continues or ends it. Replays and mismatched decisions raise
  `ResumeError`. Run state is JSON-safe and lives in a pluggable `StateStore`
  (`InMemoryStateStore` included).
- Duplicate-action stop, a wall-clock deadline checked between calls, and a
  summary pass. `run()` does not raise for model or tool failures; a tool's
  exception text never reaches the model or the result, only its type.

### Verified

- 41 tests with a scripted model (no network) pass on Python 3.10, 3.11 and
  3.12. Mutation-checked locally: removing the taint rule, the case-insensitive
  fence, the exception-text rule, the resume claim, the hard cap, the fail-closed
  default or the bool-is-not-integer check each makes at least one test fail.
- The quickstart in the README was run with the real `ragleap-tools`
  `calculator` tool and a scripted model.

### Not verified

- Any real model: no provider has been run through this loop yet.
- Long runs; concurrent resumes across processes (the store must make resume
  atomic); equivalence with RagLeap Core's agent loop (mirrors core commit
  `59fd555` as of 2026-10-03, which keeps changing).
