# Design: Cross-Chunk Relation Extraction (#154)

> **Status: Implemented (v0.8.0).**
> This document was drafted during the same session that implemented
> the feature and was not committed to the repo at the time - a real
> process gap caught during a later documentation-claims audit. It's
> recreated here after the fact, reflecting what was actually decided
> and shipped, not a pending proposal. See CHANGELOG.md for the full
> implementation summary.

**Package:** `ragleap-graph`
**Depends on / precedent:** `docs/design/schema-migrations.md`,
`docs/adr/0001-backup-restore-ownership.md`

---

## 1. Problem statement

Relation extraction ran per-chunk only: each chunk was sent to the LLM
independently, so any relation whose evidence spans a chunk boundary -
e.g. an entity introduced in chunk 1, referred to only by pronoun ("it",
"the company") in a later chunk - was never extracted. Confirmed via
source inspection: `entity_counter` already accumulated entity names
across every chunk (`_upsert_document_once()`, `__init__.py`), but
`known_entities` passed into each chunk's relation-extraction call was
chunk-local only - the fix was a threading problem, not a missing
subsystem.

## 2. What shipped

`ExtractionConfig.cross_chunk_relations` (opt-in, default `False`,
requires `extract_relations=True`): after the per-chunk loop, one
additional `LLMRelationExtractor.extract()` call runs over the full
accumulated document text and every entity found across all chunks,
feeding the *same* `relation_counter` used by the per-chunk pass - no
new Neo4j write path was needed, since the existing `RelationWeight`
aggregation and `RELATES_AS` MERGE already handle whatever lands in
`relation_counter`.

`LLMRelationExtractor.extract()` gained an optional `resolve_references`
parameter (default `False`, only set `True` by the cross-chunk call)
that adds an explicit instruction asking the model to resolve
pronouns/vague references to a known entity name - the base per-chunk
prompt gave no such instruction, and without it a 0.5B-parameter model
had no reason to infer that "it" should map to a specific known entity.

## 3. Real finding from live testing (this is the part worth keeping)

The architecture worked correctly on the first design pass - verified
by tracing the existing `RelationWeight`/`RELATES_AS` pipeline before
writing any code, so no parallel write path was ever needed.

What did NOT work on the first attempt was the model itself: `qwen2.5:0.5b`
failed to resolve a real pronoun-reference test case correctly. It didn't
just miss the relation - it produced an incorrect one
(`(Sarah Chen)-[FOUNDED_BY]->(Austin)`, connecting the wrong two
entities), which is a worse failure mode than returning nothing, since
it would silently pollute the graph rather than leave an honest gap.

A side-by-side test with Gemini (`gemini-3.5-flash` at the time, since
superseded) resolved the identical test case correctly
(`(Acme Corp)-[RELOCATED_TO]->(Austin)`), confirming this was a model
capability ceiling, not a flaw in the `resolve_references` prompt
addition or the surrounding architecture.

**Documented limitation, not silently worked around:** cross-chunk
relation extraction quality depends heavily on the provider's reasoning
capability. Small local models are not recommended for this feature
without independently verifying their output - this is stated in the
CHANGELOG, the README, and the live test's own docstring.

## 4. Non-goals (unchanged from original scope)

- General-purpose coreference resolution - only enough continuity to
  support relation extraction was implemented, not a full NLP subsystem.
- Cross-*document* relation extraction (linking entities across separate
  `upsert_document()` calls) - not attempted.
- Guaranteeing full recall of cross-chunk relations - the bar was
  "meaningfully better than zero, live-verified, honestly labeled,"
  matching this project's existing pattern for other known limitations
  (`ask_stream()` token usage, `MAX_CONTEXT_CHARS` approximation).

## 5. Verification performed

- Offline: pure-logic tests for the carry-forward/threading behavior,
  following the existing `LLMRelationExtractor` mock-based test style.
- Live: a real test document, deliberately constructed so the relation
  cannot be found by per-chunk extraction alone (chunk 2 has fewer than
  2 entities without cross-chunk context), run against real Neo4j +
  Gemini. Confirms both that `cross_chunk_relations=True` recovers the
  relation AND that `cross_chunk_relations=False` (the default) does
  not - proving the flag changes real behavior, not just that the test
  document happened to be easy.
- Full suite: 88 passed, 15 skipped at ship time (zero regressions -
  `resolve_references` defaults `False` and the cross-chunk pass is
  fully gated behind the opt-in flag).
