# Design: Ontology Cross-Validation (#152)

**Status:** Proposed — needs maintainer decision before implementation.
**Package:** `ragleap-graph`
**Depends on / precedent:** entity_types= enforcement (v0.6.3, coerces
out-of-vocabulary entity types to "UNKNOWN" post-hoc rather than relying
on prompt guidance alone)

## 1. Problem statement

`ExtractedRelation` carries only `subject`, `relation_type`, `object` as
plain strings - no entity-type information. Meanwhile, `entity_type_map`
(built in `_upsert_document_once()`, `__init__.py` ~line 519-546) already
knows each entity's type by the time relations are extracted, but that
information is never passed into `LLMRelationExtractor.extract()` or used
to validate the relation afterward. Nothing stops a nonsensical
combination like `(DATE)-[FOUNDED_BY]->(LOCATION)` from being written to
Neo4j today.

Confirmed via source inspection this session (not assumed): entity_type_map
exists in the right scope, before the relation-extraction call sites at
lines 558 and 585 - so threading it through is a contained change, not a
new subsystem.

## 2. Goals

- Give callers a way to define which relation_type values make sense
  between which entity_type pairs.
- Reject or flag relations that violate the ontology, following the same
  "enforce, don't just prompt" precedent as entity_types=.
- Stay opt-in and backward compatible - callers who don't define an
  ontology get today's unchanged behavior.

## 3. Non-goals

- Inferring an ontology automatically from data (a real, separate,
  much larger feature - not proposed here).
- A general-purpose ontology/taxonomy management system. This is scoped
  to validating relation_type against the two connected entity_types.

## 4. Real open questions - maintainer decision needed

**Q1. What shape does the caller-supplied ontology take?**
Candidate: a new `ExtractionConfig.relation_ontology` field, e.g.
```python
relation_ontology: Optional[dict[str, tuple[list[str], list[str]]]] = None
# {"FOUNDED_BY": (["ORGANIZATION"], ["PERSON"])}
```
mapping each relation_type to its allowed (subject_types, object_types).
Alternative: a flat list of allowed (subject_type, relation_type,
object_type) triples - simpler to read, more verbose to define for
many relation_types sharing the same type pair.

**Q2. What happens on an invalid combination?**
Entity types coerce silently to "UNKNOWN" (v0.6.3). Relations have no
"UNKNOWN" equivalent - dropping a relation entirely is a bigger loss
than downgrading an entity's type. Options: (a) drop the relation
silently, (b) drop it but log a warning, (c) keep it but tag it
(e.g. `ontology_valid: false` property on the RELATES_AS edge,
mirroring how cross-chunk relations got `extraction_scope: "cross_chunk"`
- actually, checking the v0.8.0 patch, that property was proposed in an
earlier draft but the shipped version doesn't write it; worth deciding
consistently for both features if (c) is chosen here).

**Q3. Does this require entity_types= to be set at all?**
An ontology is meaningless without typed entities - if entity_types= is
unset, all entities are "UNKNOWN" and no relation_type could ever be
validated against anything real. Should setting relation_ontology=
without entity_types= be a config-time ValueError (fail fast, matching
ExtractionConfig's existing __post_init__ validation style) rather than
silently validating everything against "UNKNOWN" and passing nothing?

**Q4. Does this apply to the v0.8.0 cross-chunk pass too?**
The cross-chunk relation-extraction call already reuses the exact same
LLMRelationExtractor.extract() and the same relation_counter - so yes,
by construction, unless deliberately excluded. Worth confirming this is
desired, given cross-chunk relations are already documented as more
failure-prone on weak models; ontology validation might catch some of
those failures (a bonus), or might reject cross-chunk relations at a
different rate than per-chunk ones (worth watching for once live-tested).

## 5. Verification plan (draft)

- Offline tests: valid/invalid combination pairs, dropped vs kept
  relations, config validation errors, following the same fake-double
  style as existing extraction.py tests.
- Live test: real extraction producing at least one relation that
  violates a caller-supplied ontology, confirming it's correctly
  excluded (or tagged, depending on Q2's answer) - same
  Gemini-preferred-over-small-local-model pattern established for #154,
  since ontology validation depends on the underlying relation_type/
  entity_type extraction being reasonably accurate in the first place.
