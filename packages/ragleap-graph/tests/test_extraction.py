"""
Tests for ragleap_graph.extraction (v0.2.0).

Mirrors v0.1.0's test style: pure-logic tests need no live services,
mocked-provider tests verify request/response handling without burning
real API calls, and one live test (skipped without credentials) proves
the real end-to-end path actually works.
"""
import json
import os
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Mock ragleap.generation before importing extraction, so tests run without
# ragleap-rag installed (mirrors how method="regex" has zero dependency on
# it). The mock's generate_answer() return shape matches the REAL
# GenerationService.generate_answer() dict shape confirmed against
# ragleap-rag/src/ragleap/generation.py.
# ---------------------------------------------------------------------------

class FakeProviderConfig:
    def __init__(self, provider, api_key=None, model=None, base_url=None):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url


class FakeGenerationService:
    """Set FakeGenerationService.next_response before calling extract()
    to control what generate_answer() returns for that test."""

    next_response = None

    def __init__(self, primary, default_temperature=0.3, system_prompt=None):
        self.primary = primary
        self.default_temperature = default_temperature
        self.system_prompt = system_prompt

    def generate_answer(self, query, chunks, response_format=None, temperature=None, **kw):
        return FakeGenerationService.next_response


@pytest.fixture(autouse=True)
def mock_ragleap_generation(monkeypatch):
    ragleap_pkg = types.ModuleType("ragleap")
    ragleap_gen = types.ModuleType("ragleap.generation")
    ragleap_gen.ProviderConfig = FakeProviderConfig
    ragleap_gen.GenerationService = FakeGenerationService
    monkeypatch.setitem(sys.modules, "ragleap", ragleap_pkg)
    monkeypatch.setitem(sys.modules, "ragleap.generation", ragleap_gen)
    # Bust ragleap_graph.extraction's cache so it re-imports and rebinds
    # ProviderConfig/GenerationService against the fakes above. This
    # submodule may already be cached with REAL bindings from an earlier,
    # unmocked import via ragleap_graph/__init__.py during test collection
    # (since ragleap-rag is genuinely installed in this environment) - a
    # real bug caught in this exact spot, see CHANGELOG.
    monkeypatch.delitem(sys.modules, "ragleap_graph.extraction", raising=False)

    # Canary: confirm the mock actually took effect. If it did not, tests
    # would silently make real network calls instead of using the fakes -
    # fail loudly here instead of letting that happen quietly.
    import ragleap_graph.extraction as _ext_check
    assert _ext_check.GenerationService is FakeGenerationService, (
        "Mock did not take effect - ragleap_graph.extraction is still bound "
        "to the real GenerationService. Tests would make real network calls."
    )
    yield


# ---------------------------------------------------------------------------
# ExtractionConfig — pure logic, no live services needed
# ---------------------------------------------------------------------------

def test_extraction_config_defaults_to_regex():
    from ragleap_graph.extraction import ExtractionConfig
    config = ExtractionConfig()
    assert config.method == "regex"
    assert config.dedup_enabled is False
    assert config.provider is None


def test_extraction_config_llm_requires_provider():
    from ragleap_graph.extraction import ExtractionConfig
    with pytest.raises(ValueError, match="requires provider"):
        ExtractionConfig(method="llm")


def test_extraction_config_llm_with_provider_succeeds():
    from ragleap_graph.extraction import ExtractionConfig
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    assert config.method == "llm"


def test_extraction_config_rejects_bad_dedup_threshold():
    from ragleap_graph.extraction import ExtractionConfig
    with pytest.raises(ValueError, match="dedup_threshold"):
        ExtractionConfig(dedup_threshold=1.5)
    with pytest.raises(ValueError, match="dedup_threshold"):
        ExtractionConfig(dedup_threshold=0.0)


def test_extraction_config_rejects_bad_max_entities():
    from ragleap_graph.extraction import ExtractionConfig
    with pytest.raises(ValueError, match="max_entities_per_chunk"):
        ExtractionConfig(max_entities_per_chunk=0)


# ---------------------------------------------------------------------------
# EntityDeduplicator — pure logic, no live services needed
# ---------------------------------------------------------------------------

def test_dedup_merges_punctuation_variants():
    from ragleap_graph.extraction import EntityDeduplicator
    dedup = EntityDeduplicator()
    mapping = dedup.resolve(["TC Antony", "T.C. Antony"])
    assert mapping["TC Antony"] == mapping["T.C. Antony"]


def test_dedup_merges_case_and_trailing_punctuation():
    from ragleap_graph.extraction import EntityDeduplicator
    dedup = EntityDeduplicator()
    mapping = dedup.resolve(["Acme Corp", "ACME Corp."])
    assert mapping["Acme Corp"] == mapping["ACME Corp."]


def test_dedup_default_threshold_does_not_merge_distinct_short_names():
    """Regression test for a real false-positive caught during development:
    default threshold must NOT merge 'Neo4j' and 'Neo 4j' — they are
    different entities, and naive normalization made them look identical
    at a lower threshold (0.85)."""
    from ragleap_graph.extraction import EntityDeduplicator
    dedup = EntityDeduplicator()
    mapping = dedup.resolve(["Neo4j", "Neo 4j"])
    assert mapping["Neo4j"] != mapping["Neo 4j"]


def test_dedup_canonical_form_prefers_longer_variant():
    from ragleap_graph.extraction import EntityDeduplicator
    dedup = EntityDeduplicator()
    mapping = dedup.resolve(["TC Antony", "T.C. Antony"])
    assert mapping["TC Antony"] == "T.C. Antony"


def test_dedup_empty_input_returns_empty_mapping():
    from ragleap_graph.extraction import EntityDeduplicator
    dedup = EntityDeduplicator()
    assert dedup.resolve([]) == {}


def test_dedup_rejects_invalid_threshold():
    from ragleap_graph.extraction import EntityDeduplicator
    with pytest.raises(ValueError):
        EntityDeduplicator(threshold=0.0)
    with pytest.raises(ValueError):
        EntityDeduplicator(threshold=1.5)


# ---------------------------------------------------------------------------
# LLMEntityExtractor — mocked GenerationService, no real API calls
# ---------------------------------------------------------------------------

def test_llm_extractor_requires_llm_method():
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor
    config = ExtractionConfig()  # defaults to method="regex"
    with pytest.raises(ValueError, match="requires ExtractionConfig"):
        LLMEntityExtractor(config)


def test_llm_extractor_empty_text_returns_empty_without_calling_provider():
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    extractor = LLMEntityExtractor(config)
    assert extractor.extract("") == []
    assert extractor.extract("   ") == []


def test_llm_extractor_parses_native_structured_response():
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor
    FakeGenerationService.next_response = {
        "answer": json.dumps({"entities": [{"name": "Acme Corp", "type": "ORG"}]}),
        "provider_used": "gemini",
        "structured": {"entities": [{"name": "Acme Corp", "type": "ORG"}]},
        "structured_valid": True,
        "structured_enforcement": "native",
    }
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    entities = LLMEntityExtractor(config).extract("Acme Corp reported strong Q3 revenue.")
    assert len(entities) == 1
    assert entities[0].name == "Acme Corp"
    assert entities[0].type == "ORG"


def test_llm_extractor_falls_back_to_parsing_raw_answer():
    """structured_valid can be False even when the provider actually
    returned usable JSON — verify the raw-answer fallback path works."""
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor
    FakeGenerationService.next_response = {
        "answer": json.dumps({"entities": [{"name": "Neo4j", "type": "PRODUCT"}]}),
        "provider_used": "together",
        "structured": None,
        "structured_valid": False,
        "structured_enforcement": "json_object_fallback",
    }
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="together"))
    entities = LLMEntityExtractor(config).extract("Neo4j is a graph database.")
    assert len(entities) == 1
    assert entities[0].name == "Neo4j"


def test_llm_extractor_raises_when_all_providers_failed():
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor
    FakeGenerationService.next_response = {
        "answer": "Sorry, all configured providers failed. Last error: auth failed",
        "provider_used": None,
        "structured": None,
        "structured_valid": False,
        "structured_enforcement": None,
    }
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    with pytest.raises(RuntimeError, match="all configured providers"):
        LLMEntityExtractor(config).extract("some text")


def test_llm_extractor_raises_on_malformed_response():
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor
    FakeGenerationService.next_response = {
        "answer": "not valid json at all",
        "provider_used": "gemini",
        "structured": None,
        "structured_valid": False,
        "structured_enforcement": None,
    }
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    with pytest.raises(ValueError, match="Malformed extraction response"):
        LLMEntityExtractor(config).extract("some text")


def test_llm_extractor_deduplicates_repeated_entities_case_insensitively():
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor
    FakeGenerationService.next_response = {
        "answer": json.dumps({"entities": [
            {"name": "Acme Corp", "type": "ORG"},
            {"name": "acme corp", "type": "ORG"},
        ]}),
        "provider_used": "gemini",
        "structured": {"entities": [
            {"name": "Acme Corp", "type": "ORG"},
            {"name": "acme corp", "type": "ORG"},
        ]},
        "structured_valid": True,
        "structured_enforcement": "native",
    }
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    entities = LLMEntityExtractor(config).extract("Acme Corp mentioned twice.")
    assert len(entities) == 1


def test_llm_extractor_respects_max_entities_per_chunk():
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor
    many_entities = [{"name": f"Entity{i}", "type": "MISC"} for i in range(10)]
    FakeGenerationService.next_response = {
        "answer": json.dumps({"entities": many_entities}),
        "provider_used": "gemini",
        "structured": {"entities": many_entities},
        "structured_valid": True,
        "structured_enforcement": "native",
    }
    config = ExtractionConfig(
        method="llm", provider=FakeProviderConfig(provider="gemini"), max_entities_per_chunk=3
    )
    entities = LLMEntityExtractor(config).extract("text with many entities")
    assert len(entities) == 3


def test_llm_extractor_passes_domain_terms_into_instruction():
    """Verify domain_terms= actually reaches the prompt sent to the
    provider — not just accepted and silently dropped."""
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor

    captured = {}

    class CapturingService(FakeGenerationService):
        def generate_answer(self, query, chunks, response_format=None, temperature=None, **kw):
            captured["query"] = query
            return {
                "answer": json.dumps({"entities": []}),
                "provider_used": "gemini",
                "structured": {"entities": []},
                "structured_valid": True,
                "structured_enforcement": "native",
            }

    import ragleap_graph.extraction as extraction_module
    extraction_module.GenerationService = CapturingService

    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    LLMEntityExtractor(config).extract("some text", domain_terms=["ALARA", "dose limits"])
    assert "ALARA" in captured["query"]
    assert "dose limits" in captured["query"]


# ---------------------------------------------------------------------------
# Live integration test — real LLM call, real structured extraction.
# Skips cleanly without credentials, same pattern as v0.1.0's
# test_live_full_roundtrip for Neo4j.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="No GEMINI_API_KEY in environment — skipping real live LLM call.",
)
def test_live_llm_extraction_roundtrip(monkeypatch):
    """Real end-to-end test: actual Gemini call, actual structured
    extraction, actual parsing — no mocks. Mirrors v0.1.0's
    test_live_full_roundtrip pattern for Neo4j: runs automatically when
    real credentials are present, skips cleanly otherwise.

    Explicitly un-mocks ragleap_graph.extraction for this one test, since
    the autouse fixture above replaces ragleap.generation with fakes for
    every other test in this module.
    """
    monkeypatch.delitem(sys.modules, "ragleap", raising=False)
    monkeypatch.delitem(sys.modules, "ragleap.generation", raising=False)
    monkeypatch.delitem(sys.modules, "ragleap_graph.extraction", raising=False)

    from ragleap.generation import ProviderConfig
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor

    real_config = ExtractionConfig(
        method="llm",
        provider=ProviderConfig(
            provider="gemini",
            api_key=os.environ["GEMINI_API_KEY"],
            model=os.environ.get("GEMINI_CHAT_MODEL", "gemini-3.6-flash"),
        ),
    )
    extractor = LLMEntityExtractor(real_config)
    entities = extractor.extract(
        "Acme Corporation reported strong Q3 revenue growth, driven by "
        "their new product line launched in partnership with Neo4j Inc."
    )

    assert len(entities) > 0, "Live extraction returned zero entities"
    names_lower = [e.name.lower() for e in entities]
    assert any("acme" in n for n in names_lower), (
        f"Expected an Acme-related entity in live extraction, got: {names_lower}"
    )


# ---------------------------------------------------------------------------
# LLMRelationExtractor (v0.4.0) - mocked GenerationService, no real API calls
# ---------------------------------------------------------------------------

def test_extraction_config_extract_relations_requires_llm_method():
    from ragleap_graph.extraction import ExtractionConfig
    with pytest.raises(ValueError, match="extract_relations=True requires method='llm'"):
        ExtractionConfig(extract_relations=True)  # defaults to method="regex"


def test_extraction_config_extract_relations_with_llm_method_succeeds():
    from ragleap_graph.extraction import ExtractionConfig
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"), extract_relations=True)
    assert config.extract_relations is True


def test_relation_extractor_requires_llm_method():
    from ragleap_graph.extraction import ExtractionConfig, LLMRelationExtractor
    config = ExtractionConfig()  # method="regex"
    with pytest.raises(ValueError, match="requires ExtractionConfig"):
        LLMRelationExtractor(config)


def test_relation_extractor_skips_llm_call_with_fewer_than_two_entities():
    """A relation needs 2 entities to connect - verify no LLM call
    happens when there's only 0 or 1 known entities, by making the
    generator explode if invoked."""
    from ragleap_graph.extraction import ExtractionConfig, LLMRelationExtractor

    def _explode(self, *a, **kw):
        raise AssertionError("should not call generate_answer with <2 known entities")
    FakeGenerationService.generate_answer = _explode

    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    extractor = LLMRelationExtractor(config)

    assert extractor.extract("some text", known_entities=[]) == []
    assert extractor.extract("some text", known_entities=["Acme Corp"]) == []

    # restore normal behavior for subsequent tests
    FakeGenerationService.generate_answer = lambda self, query, chunks, response_format=None, temperature=None, **kw: FakeGenerationService.next_response


def test_relation_extractor_parses_valid_relations():
    from ragleap_graph.extraction import ExtractionConfig, LLMRelationExtractor
    FakeGenerationService.next_response = {
        "answer": json.dumps({"relations": [
            {"subject": "Acme Corp", "relation_type": "reported", "object": "Q3 revenue growth"},
        ]}),
        "provider_used": "gemini",
        "structured": {"relations": [
            {"subject": "Acme Corp", "relation_type": "reported", "object": "Q3 revenue growth"},
        ]},
        "structured_valid": True,
        "structured_enforcement": "native",
    }
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    extractor = LLMRelationExtractor(config)
    relations = extractor.extract(
        "Acme Corp reported strong Q3 revenue growth.",
        known_entities=["Acme Corp", "Q3 revenue growth"],
    )
    assert len(relations) == 1
    assert relations[0].subject == "Acme Corp"
    assert relations[0].relation_type == "REPORTED"  # uppercased
    assert relations[0].object == "Q3 revenue growth"


def test_relation_extractor_drops_hallucinated_entities():
    """Even though the prompt constrains subject/object to known
    entities, verify the defensive filter actually drops a relation
    referencing an entity name that isn't in known_entities."""
    from ragleap_graph.extraction import ExtractionConfig, LLMRelationExtractor
    FakeGenerationService.next_response = {
        "answer": json.dumps({"relations": [
            {"subject": "Acme Corp", "relation_type": "REPORTED", "object": "Q3 revenue growth"},
            {"subject": "Globex Inc", "relation_type": "ACQUIRED", "object": "Neo4j"},
        ]}),
        "provider_used": "gemini",
        "structured": {"relations": [
            {"subject": "Acme Corp", "relation_type": "REPORTED", "object": "Q3 revenue growth"},
            {"subject": "Globex Inc", "relation_type": "ACQUIRED", "object": "Neo4j"},
        ]},
        "structured_valid": True,
        "structured_enforcement": "native",
    }
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    extractor = LLMRelationExtractor(config)
    relations = extractor.extract(
        "text", known_entities=["Acme Corp", "Q3 revenue growth"],  # "Globex Inc" and "Neo4j" NOT known
    )
    assert len(relations) == 1
    assert relations[0].subject == "Acme Corp"


def test_relation_extractor_drops_self_relations():
    from ragleap_graph.extraction import ExtractionConfig, LLMRelationExtractor
    FakeGenerationService.next_response = {
        "answer": json.dumps({"relations": [{"subject": "Acme Corp", "relation_type": "IS", "object": "Acme Corp"}]}),
        "provider_used": "gemini",
        "structured": {"relations": [{"subject": "Acme Corp", "relation_type": "IS", "object": "Acme Corp"}]},
        "structured_valid": True,
        "structured_enforcement": "native",
    }
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    extractor = LLMRelationExtractor(config)
    relations = extractor.extract("text", known_entities=["Acme Corp", "Other Entity"])
    assert relations == []


def test_relation_extractor_raises_when_all_providers_failed():
    from ragleap_graph.extraction import ExtractionConfig, LLMRelationExtractor
    FakeGenerationService.next_response = {
        "answer": "Sorry, all configured providers failed. Last error: auth failed",
        "provider_used": None,
        "structured": None,
        "structured_valid": False,
        "structured_enforcement": None,
    }
    config = ExtractionConfig(method="llm", provider=FakeProviderConfig(provider="gemini"))
    extractor = LLMRelationExtractor(config)
    with pytest.raises(RuntimeError, match="all configured providers"):
        extractor.extract("text", known_entities=["A", "B"])


# ---------------------------------------------------------------------------
# ExtractionConfig.entity_types (v0.5.0) - mocked GenerationService
# ---------------------------------------------------------------------------

def test_extraction_config_entity_types_defaults_to_none():
    from ragleap_graph.extraction import ExtractionConfig
    config = ExtractionConfig()
    assert config.entity_types is None


def test_llm_extractor_passes_entity_types_into_instruction():
    """Verify entity_types= actually reaches the prompt sent to the
    provider - not just accepted and silently dropped."""
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor

    captured = {}

    class CapturingService(FakeGenerationService):
        def generate_answer(self, query, chunks, response_format=None, temperature=None, **kw):
            captured["query"] = query
            return {
                "answer": json.dumps({"entities": []}),
                "provider_used": "gemini",
                "structured": {"entities": []},
                "structured_valid": True,
                "structured_enforcement": "native",
            }

    import ragleap_graph.extraction as extraction_module
    extraction_module.GenerationService = CapturingService

    config = ExtractionConfig(
        method="llm",
        provider=FakeProviderConfig(provider="gemini"),
        entity_types=["Customer", "Product", "Ticket"],
    )
    LLMEntityExtractor(config).extract("some text")
    assert "Customer" in captured["query"]
    assert "Product" in captured["query"]
    assert "Ticket" in captured["query"]


def test_llm_extractor_still_returns_type_field_from_response():
    """Regression guard: entity_types= guidance must not break the
    existing per-entity type field already returned by extract() since
    v0.2.0 - it just influences what values that field tends to hold."""
    from ragleap_graph.extraction import ExtractionConfig, LLMEntityExtractor
    FakeGenerationService.next_response = {
        "answer": json.dumps({"entities": [{"name": "Acme Corp", "type": "Customer"}]}),
        "provider_used": "gemini",
        "structured": {"entities": [{"name": "Acme Corp", "type": "Customer"}]},
        "structured_valid": True,
        "structured_enforcement": "native",
    }
    config = ExtractionConfig(
        method="llm",
        provider=FakeProviderConfig(provider="gemini"),
        entity_types=["Customer", "Product"],
    )
    entities = LLMEntityExtractor(config).extract("Acme Corp is a customer.")
    assert len(entities) == 1
    assert entities[0].type == "Customer"
