# ragleap-graph Versioning Policy (Draft — v1.0 readiness proposal)

**Status: DRAFT.** This is a proposal for what a `v1.0` stability
commitment would mean, written to be reviewed and either adopted,
amended, or rejected by the maintainer. It is not itself a commitment
until the maintainer says so — drafting the policy is not the same as
adopting it.

## Why this matters

`ragleap-graph` is currently pre-1.0 (`Development Status :: 3 - Alpha`
in `pyproject.toml`), which under standard SemVer convention means
breaking changes can happen in any release without a major version
bump. That's honest for where the library is today, but it's also a
real blocker for enterprise adoption — teams building on top of a
library need to know what they can rely on not changing underneath
them. This document proposes what "stable" would mean here, concretely,
against the real current API — not a generic SemVer explainer.

## What "stable" would mean, applied to the real current surface

If adopted, a `v1.0.0` release would commit to the following being
stable (no breaking changes without a major version bump):

**Classes and their constructor signatures:**
- `GraphConfig(uri=, user=, password=)`
- `GraphIndex(config=, extraction=, audit=)`
- `ExtractionConfig(method=, provider=, dedup_enabled=, dedup_threshold=, extract_relations=, entity_types=)`
- `AuditConfig(database_url=)`

**Public methods on `GraphIndex` (signatures and return shapes):**
- `upsert_document(document_id, title, chunks, namespace=, user_id=, max_entities=, max_pairs=, domain_terms=)` → summary dict
- `find_documents_by_entities(entity_names, namespace=, user_id=, limit=)` → list of dicts
- `search_related_entities(entity_names, namespace=, user_id=, max_depth=, limit=)` → list of dicts
- `document_entities(document_id, namespace=, user_id=)` → list of dicts
- `find_relations(entity_name, relation_type=, namespace=, user_id=, limit=, direction=)` → list of dicts
- `find_entities_by_type(entity_type, namespace=, user_id=, limit=)` → list of dicts
- `find_lineage(entity_a, entity_b, relation_type=, namespace=, user_id=, limit=)` → list of dicts
- `backfill_user_id_defaults(namespace=)` → dict of counts
- `extract_query_entities(query, max_entities=, domain_terms=)` → list of strings
- `health_check()` → bool
- `close()`, `__enter__`, `__exit__`

**Explicitly NOT covered by this stability commitment:**
- Anything prefixed with `_` (e.g. `_collect_entities_for_chunk`,
  `_normalize_entity_name`, the entire `ragleap_graph._audit` module's
  internals beyond the public `AuditConfig`/`AuditLogger` classes it
  exports) - these are implementation details and may change freely
  even after 1.0.
- The exact Neo4j graph schema (node labels, property names like
  `PairWeight`/`RelationWeight`) - this is treated as an internal
  storage detail, not a public contract. Only the public method return
  values are covered.
- Performance characteristics (query latency, memory use) - covered
  by the eval/benchmark work (separate item), not by this versioning
  policy.
- Anything explicitly marked experimental in its own docstring at
  release time.

## What counts as a breaking change (needs a major version bump)

- Removing or renaming a public class, method, or constructor parameter
  listed above.
- Changing a method's return type or the shape/keys of a returned
  dict/list of dicts in a way that would break code written against
  the documented shape.
- Changing a default value in a way that changes behavior for existing
  callers who didn't explicitly set that parameter (e.g. changing
  `direction="outgoing"`'s default would be breaking; adding a new
  optional parameter with a default that doesn't change existing
  behavior is not).
- Changing what exceptions a method can raise, in a way that would
  break existing `except` handling.

## What does NOT count as breaking (fine for a minor/patch release)

- Adding new optional parameters with backward-compatible defaults
  (this is exactly the pattern used for `user_id=` and `audit=` this
  session - both added as optional, defaulting to today's behavior).
- Adding new public methods.
- Fixing a bug where the previous behavior was already documented as
  wrong, or contradicted its own docstring (matching this project's
  "honest CHANGELOG, not silently rewritten" discipline) - though even
  here, a deprecation warning for one minor version first is preferred
  where practical.
- Internal performance improvements that don't change observable
  behavior.

## Deprecation policy (proposed)

1. A method/parameter slated for removal gets a `DeprecationWarning`
   for at least one full minor version cycle before removal.
2. The CHANGELOG entry for the deprecating release states the
   replacement (if any) and the planned removal version.
3. Removal happens only in a major version release, never a minor or
   patch release.

## Open questions for the maintainer to decide

- Is the project ready to commit to this now, or should 1.0 wait until
  the eval framework and load/concurrency testing items are further
  along, so "stable" also means "proven under real load"?
- Should the Neo4j schema itself (node labels/properties) become part
  of the public contract eventually, e.g. for tooling that reads the
  graph directly rather than through the Python API? Proposed default
  above is no - keep it internal - but this is a real design choice,
  not a foregone conclusion.
- Should there be a formal "supported Python versions" commitment
  alongside this (currently `>=3.10` in `pyproject.toml`, no explicit
  policy on when that floor moves)?
