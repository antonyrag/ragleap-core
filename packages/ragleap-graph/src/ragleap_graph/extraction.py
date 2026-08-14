"""
ragleap_graph.extraction

v0.2.0 addition: optional LLM-based entity extraction and entity
deduplication, layered on top of the v0.1.0 regex extraction path.

Design constraints (locked, see CHANGELOG for rationale):
  - Default extraction method stays "regex" — zero behavior change on
    upgrade for existing users.
  - LLM extraction reuses ragleap-rag's ProviderConfig rather than
    inventing a second provider abstraction.
  - Dedup is a separate opt-in flag from extraction method, since regex
    extraction can also benefit from it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal, Optional

try:
    # Reuse ragleap-rag's existing provider abstraction rather than
    # building a second one. ragleap-graph declares ragleap-rag as an
    # optional dependency for this feature only — regex-only users don't
    # need it installed.
    #
    # Confirmed against the real source (ragleap/generation.py):
    # GenerationService.generate_answer(..., response_format=<json schema>)
    # already enforces structured JSON output across Gemini (native
    # response_schema), Anthropic (forced single tool-use call), and
    # OpenAI-compatible providers (json_schema, honestly falling back to
    # json_object if a provider doesn't support strict mode) — with the
    # actual enforcement method reported back in the result. That's
    # exactly what entity extraction needs, so LLMEntityExtractor is
    # built on top of it rather than inventing a second, parallel
    # structured-output mechanism.
    from ragleap.generation import ProviderConfig, GenerationService
except ImportError:  # pragma: no cover - exercised when ragleap-rag absent
    ProviderConfig = None  # type: ignore[assignment,misc]
    GenerationService = None  # type: ignore[assignment,misc]


ExtractionMethod = Literal["regex", "llm"]


@dataclass
class ExtractionConfig:
    """Configuration for entity extraction and deduplication.

    Parameters
    ----------
    method:
        "regex" (default, v0.1.0 behavior, no LLM calls) or "llm"
        (function-calling extraction via a ragleap-rag ProviderConfig).
    provider:
        Required when method="llm". A ragleap.ProviderConfig instance.
        Ignored when method="regex".
    dedup_enabled:
        If True, run entity names through EntityDeduplicator before
        nodes are written to Neo4j. Independent of `method` — regex
        extraction benefits from this too (e.g. "Acme Corp" vs
        "ACME Corp.").
    dedup_threshold:
        Similarity cutoff (0.0-1.0) above which two entity names are
        merged into one canonical node. Only used when dedup_enabled.
    max_entities_per_chunk:
        Passed through to whichever extractor is active.
    """

    method: ExtractionMethod = "regex"
    provider: Optional["ProviderConfig"] = None
    dedup_enabled: bool = False
    dedup_threshold: float = 0.92
    max_entities_per_chunk: int = 25
    extract_relations: bool = False
    entity_types: Optional[list[str]] = None

    def __post_init__(self) -> None:
        if self.extract_relations and self.method != "llm":
            raise ValueError(
                "extract_relations=True requires method='llm' - relation "
                "extraction has no regex equivalent, unlike entity extraction."
            )
        if self.method == "llm" and self.provider is None:
            raise ValueError(
                "ExtractionConfig(method='llm') requires provider=... "
                "(a ragleap.ProviderConfig instance)."
            )
        if self.method == "llm" and ProviderConfig is None:
            raise ImportError(
                "method='llm' requires the 'ragleap-rag' package. "
                "Install it with: pip install ragleap-rag"
            )
        if not 0.0 < self.dedup_threshold <= 1.0:
            raise ValueError("dedup_threshold must be in (0.0, 1.0]")
        if self.max_entities_per_chunk < 1:
            raise ValueError("max_entities_per_chunk must be >= 1")


# Passed as response_format= to GenerationService.generate_answer(). This
# is a plain JSON Schema object, NOT an Anthropic-style tool definition —
# generate_answer() itself handles wrapping it correctly per-provider
# (native schema / forced tool-use / json_schema), so extraction.py stays
# provider-agnostic and doesn't duplicate that per-provider logic.
_ENTITY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The entity's name exactly as it appears in the text.",
                    },
                    "type": {
                        "type": "string",
                        "description": (
                            "Entity category, e.g. PERSON, ORG, PRODUCT, "
                            "DATE, LOCATION, or a domain-specific type."
                        ),
                    },
                },
                "required": ["name", "type"],
            },
        }
    },
    "required": ["entities"],
}

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract named entities from text. Only extract entities "
    "explicitly present in the given text — never invent or infer "
    "entities that aren't stated. Respond using the required structure "
    "only; do not include any commentary outside it."
)


@dataclass
class ExtractedEntity:
    """A single extracted entity, typed (unlike v0.1.0's plain strings)."""

    name: str
    type: str = "UNKNOWN"


class LLMEntityExtractor:
    """LLM-based entity extraction via ragleap-rag's GenerationService.

    Built on GenerationService.generate_answer(response_format=...)
    rather than a hand-rolled provider client — that method already
    handles the real per-provider structured-output differences
    (Gemini native schema, Anthropic forced tool-use, OpenAI-compatible
    json_schema/json_object fallback), tested and shipped in
    ragleap-rag. No new per-provider logic is introduced here.

    Kept intentionally separate from the regex path in
    ragleap_graph.__init__ rather than merged into it, so the default
    (regex) code path has zero new dependencies or failure modes.
    """

    def __init__(self, config: ExtractionConfig) -> None:
        if config.method != "llm":
            raise ValueError("LLMEntityExtractor requires ExtractionConfig(method='llm')")
        if GenerationService is None:
            raise ImportError(
                "LLMEntityExtractor requires the 'ragleap-rag' package. "
                "Install it with: pip install ragleap-rag"
            )
        self._config = config
        # temperature=0.0: extraction wants deterministic, literal recall
        # of what's in the text, not creative variation.
        self._service = GenerationService(
            primary=config.provider,
            default_temperature=0.0,
            system_prompt=_EXTRACTION_SYSTEM_PROMPT,
        )

    def extract(self, text: str, domain_terms: Optional[list[str]] = None) -> list[ExtractedEntity]:
        """Extract entities from `text` using the configured LLM provider.

        `domain_terms` is passed through as extra guidance in the prompt,
        mirroring the v0.1.0 `domain_terms=` convention on the regex path
        — no hardcoded vocabulary, caller supplies their own.
        """
        if not text or not text.strip():
            return []

        instruction = self._build_instruction(domain_terms)
        # generate_answer() is shaped around (query, chunks) for RAG, but
        # its context-building/response_format machinery works fine for
        # a single-chunk extraction call: the "query" is our fixed
        # extraction instruction, and the "chunk" is the text to extract
        # from. This reuses generate_answer()'s tested trimming, citation,
        # and structured-output logic rather than re-implementing it.
        result = self._service.generate_answer(
            query=instruction,
            chunks=[{"text": text, "document_name": "extraction_input", "chunk_index": 0}],
            response_format=_ENTITY_JSON_SCHEMA,
            temperature=0.0,
        )

        if result.get("provider_used") is None:
            raise RuntimeError(
                f"LLM entity extraction failed on all configured providers: {result.get('answer')}"
            )

        return self._parse_result(result)

    def _build_instruction(self, domain_terms: Optional[list[str]]) -> str:
        base = "Extract all named entities from the given text."
        if self._config.entity_types:
            types_joined = ", ".join(self._config.entity_types)
            base += (
                f" Where an entity fits one of these categories, use that "
                f"category as its type: {types_joined}. Use your own "
                f"judgment for entities that do not fit any of these."
            )
        if not domain_terms:
            return base
        joined = ", ".join(domain_terms)
        return base + (
            f" Pay particular attention to these known domain terms if present: {joined}."
        )

    def _parse_result(self, result: dict[str, Any]) -> list[ExtractedEntity]:
        entities_raw: Optional[list[dict[str, Any]]] = None

        if result.get("structured_valid") and isinstance(result.get("structured"), dict):
            entities_raw = result["structured"].get("entities")

        if entities_raw is None:
            # structured_valid can be False even when enforcement was
            # "native", if the provider technically returned valid JSON
            # that didn't match the schema shape exactly. Fall back to
            # parsing the raw answer text directly before giving up.
            try:
                fallback = json.loads(result.get("answer", ""))
                entities_raw = fallback.get("entities") if isinstance(fallback, dict) else None
            except (json.JSONDecodeError, AttributeError):
                entities_raw = None

        if entities_raw is None:
            raise ValueError(
                f"Malformed extraction response from provider "
                f"'{result.get('provider_used')}' "
                f"(enforcement={result.get('structured_enforcement')}): "
                f"{result.get('answer')!r}"
            )

        entities: list[ExtractedEntity] = []
        seen: set[str] = set()
        for item in entities_raw[: self._config.max_entities_per_chunk]:
            name = str(item.get("name", "")).strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            raw_type = str(item.get("type", "UNKNOWN"))
            # v0.6.3: entity_types= is now enforced, not just guidance.
            # A model can and will occasionally return a type outside
            # the caller-supplied list even with prompt guidance -
            # coerce those to "UNKNOWN" rather than accepting an
            # arbitrary out-of-vocabulary value, consistent with how
            # regex-extracted entities already use "UNKNOWN" when there
            # is no reliable type available. Only applies when
            # entity_types= is actually set - without it, any type the
            # model returns is accepted as-is (unchanged default).
            if self._config.entity_types and raw_type not in self._config.entity_types:
                entity_type = "UNKNOWN"
            else:
                entity_type = raw_type
            entities.append(ExtractedEntity(name=name, type=entity_type))
        return entities


class EntityDeduplicator:
    """Merge near-duplicate entity names into one canonical form.

    Independent of extraction method — works on any list of entity name
    strings, whether produced by the regex path or the LLM path.
    """

    def __init__(self, threshold: float = 0.92) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError("threshold must be in (0.0, 1.0]")
        self._threshold = threshold

    def resolve(self, names: list[str]) -> dict[str, str]:
        """Return a mapping of {original_name: canonical_name}.

        Canonical form is chosen as the longest variant seen (heuristic:
        "T.C. Antony" over "TC Antony" tends to preserve more information).
        Pure string-similarity based; no embeddings required, so this
        works with zero extra dependencies even when method="regex".
        """
        if not names:
            return {}

        normalized = [(n, self._normalize(n)) for n in names]
        clusters: list[list[str]] = []

        for name, norm in normalized:
            placed = False
            for cluster in clusters:
                cluster_norm = self._normalize(cluster[0])
                if self._similarity(norm, cluster_norm) >= self._threshold:
                    cluster.append(name)
                    placed = True
                    break
            if not placed:
                clusters.append([name])

        mapping: dict[str, str] = {}
        for cluster in clusters:
            canonical = max(cluster, key=len)
            for name in cluster:
                mapping[name] = canonical
        return mapping

    @staticmethod
    def _normalize(name: str) -> str:
        collapsed = re.sub(r"[.\-_,]", "", name.lower())
        collapsed = re.sub(r"\s+", " ", collapsed).strip()
        return collapsed

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()


_RELATION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "Name of the subject entity. Must exactly match one of the provided known entity names.",
                    },
                    "relation_type": {
                        "type": "string",
                        "description": "Relationship type in UPPER_SNAKE_CASE, e.g. REPORTED, LAUNCHED, PARTNERED_WITH, ACQUIRED.",
                    },
                    "object": {
                        "type": "string",
                        "description": "Name of the object entity. Must exactly match one of the provided known entity names.",
                    },
                },
                "required": ["subject", "relation_type", "object"],
            },
        }
    },
    "required": ["relations"],
}

_RELATION_SYSTEM_PROMPT = (
    "You identify relationships between named entities in text. Only "
    "identify relationships explicitly stated or clearly implied by the "
    "text - never invent relationships not supported by it. Both the "
    "subject and object of every relation must be exactly one of the "
    "provided known entity names - do not introduce new entity names."
)


@dataclass
class ExtractedRelation:
    """A single typed relation between two known entities."""

    subject: str
    relation_type: str
    object: str


class LLMRelationExtractor:
    """
    Identifies typed relations between an already-known set of entities
    in a piece of text.

    Deliberately takes known_entities= as an explicit parameter rather
    than extracting entities itself - constrains the LLM's subject/object
    choices to entities already extracted and normalized (by either the
    regex or LLM entity-extraction path), which both reduces hallucinated
    entities and reuses the existing, tested entity extraction rather
    than duplicating it.
    """

    def __init__(self, config: ExtractionConfig) -> None:
        if config.method != "llm":
            raise ValueError("LLMRelationExtractor requires ExtractionConfig(method='llm')")
        if GenerationService is None:
            raise ImportError(
                "LLMRelationExtractor requires the 'ragleap-rag' package. "
                "Install it with: pip install ragleap-rag"
            )
        self._config = config
        self._service = GenerationService(
            primary=config.provider,
            default_temperature=0.0,
            system_prompt=_RELATION_SYSTEM_PROMPT,
        )

    def extract(
        self,
        text: str,
        known_entities: list[str],
        domain_terms: Optional[list[str]] = None,
    ) -> list[ExtractedRelation]:
        """
        Identify relations between known_entities as they appear in text.
        Returns [] without any LLM call if fewer than 2 entities are
        known - a relation needs at least two entities to connect, so
        there is nothing to ask for and no reason to spend a call.
        """
        if not text or not text.strip() or len(known_entities) < 2:
            return []

        instruction = self._build_instruction(known_entities, domain_terms)
        result = self._service.generate_answer(
            query=instruction,
            chunks=[{"text": text, "document_name": "relation_extraction_input", "chunk_index": 0}],
            response_format=_RELATION_JSON_SCHEMA,
            temperature=0.0,
        )

        if result.get("provider_used") is None:
            raise RuntimeError(
                f"LLM relation extraction failed on all configured providers: {result.get('answer')}"
            )

        return self._parse_result(result, known_entities)

    def _build_instruction(self, known_entities: list[str], domain_terms: Optional[list[str]]) -> str:
        entity_list = ", ".join(known_entities)
        base = f"Identify relationships between these known entities: {entity_list}."
        if domain_terms:
            joined = ", ".join(domain_terms)
            base += f" Pay particular attention to these known domain terms if present: {joined}."
        return base

    def _parse_result(self, result: dict[str, Any], known_entities: list[str]) -> list[ExtractedRelation]:
        relations_raw: Optional[list[dict[str, Any]]] = None

        if result.get("structured_valid") and isinstance(result.get("structured"), dict):
            relations_raw = result["structured"].get("relations")

        if relations_raw is None:
            try:
                fallback = json.loads(result.get("answer", ""))
                relations_raw = fallback.get("relations") if isinstance(fallback, dict) else None
            except (json.JSONDecodeError, AttributeError):
                relations_raw = None

        if relations_raw is None:
            raise ValueError(
                f"Malformed relation extraction response from provider "
                f"'{result.get('provider_used')}': {result.get('answer')!r}"
            )

        # Defensive validation: even though the prompt constrains subject/
        # object to known_entities, the LLM can still hallucinate a name
        # not in that list - drop (do not crash on) any relation where
        # either side is not a known entity, rather than trusting the
        # model's compliance blindly.
        known_lower = {e.lower() for e in known_entities}
        relations: list[ExtractedRelation] = []
        for item in relations_raw:
            subject = str(item.get("subject", "")).strip()
            relation_type = str(item.get("relation_type", "")).strip().upper()
            obj = str(item.get("object", "")).strip()
            if not subject or not relation_type or not obj:
                continue
            if subject.lower() not in known_lower or obj.lower() not in known_lower:
                continue
            if subject.lower() == obj.lower():
                continue
            relations.append(ExtractedRelation(subject=subject, relation_type=relation_type, object=obj))
        return relations
