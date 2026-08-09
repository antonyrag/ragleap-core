"""
Tests for ragleap_graph.

Three tiers, mirroring ragleap-rag's own test discipline:
1. Pure logic tests — no Neo4j needed (normalization, extraction, validation)
2. Driver-unavailable safety tests — confirm graceful degradation
3. Live integration test — real Neo4j round-trip, skipped automatically
   unless NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD are set in the environment.
   Cleans up its own test data via namespace-scoped delete, same pattern
   manually verified during development.
"""
import os

import pytest

from ragleap_graph import GraphConfig, GraphIndex, MAX_ALLOWED_DEPTH


# ---------------------------------------------------------------------------
# GraphConfig
# ---------------------------------------------------------------------------

def test_graph_config_defaults():
    config = GraphConfig()
    assert config.uri == "bolt://localhost:7687"
    assert config.user == "neo4j"
    assert config.password == ""


def test_graph_config_custom_values():
    config = GraphConfig(uri="bolt://example.com:7687", user="admin", password="secret")
    assert config.uri == "bolt://example.com:7687"
    assert config.user == "admin"
    assert config.password == "secret"


# ---------------------------------------------------------------------------
# Entity normalization (pure logic, no driver needed)
# ---------------------------------------------------------------------------

@pytest.fixture
def graph_no_driver():
    """A GraphIndex whose driver never connects (bad URI) — safe for
    testing pure logic methods without touching a real database."""
    config = GraphConfig(uri="bolt://localhost:1", user="x", password="x")
    g = GraphIndex(config=config)
    assert g.driver is None
    return g


def test_normalize_entity_name_empty(graph_no_driver):
    assert graph_no_driver._normalize_entity_name("") == ""
    assert graph_no_driver._normalize_entity_name(None) == ""


def test_normalize_entity_name_too_short(graph_no_driver):
    assert graph_no_driver._normalize_entity_name("ab") == ""


def test_normalize_entity_name_collapses_whitespace(graph_no_driver):
    result = graph_no_driver._normalize_entity_name("Acme   Corp\n\tInc")
    assert result == "Acme Corp Inc"


def test_normalize_entity_name_strips_punctuation(graph_no_driver):
    result = graph_no_driver._normalize_entity_name("  (Acme Corp).  ")
    assert result == "Acme Corp"


def test_normalize_entity_name_keeps_acronyms_uppercase(graph_no_driver):
    assert graph_no_driver._normalize_entity_name("ALARA") == "ALARA"
    assert graph_no_driver._normalize_entity_name("IAEA") == "IAEA"


def test_normalize_entity_name_title_cases_normal_phrases(graph_no_driver):
    assert graph_no_driver._normalize_entity_name("acme corp") == "Acme Corp"
    assert graph_no_driver._normalize_entity_name("ACME corp") == "Acme Corp"


def test_normalize_entity_name_truncates_long_names(graph_no_driver):
    long_name = "A" * 200
    result = graph_no_driver._normalize_entity_name(long_name)
    assert len(result) == 120


# ---------------------------------------------------------------------------
# Entity extraction (pure logic, no driver needed)
# ---------------------------------------------------------------------------

def test_extract_entities_empty_text(graph_no_driver):
    assert graph_no_driver._extract_entity_candidates_from_text("") == []


def test_extract_entities_finds_acronyms(graph_no_driver):
    result = graph_no_driver._extract_entity_candidates_from_text(
        "The IAEA published new guidelines."
    )
    assert "IAEA" in result


def test_extract_entities_finds_capitalized_phrases(graph_no_driver):
    result = graph_no_driver._extract_entity_candidates_from_text(
        "Acme Corp signed a deal with Globex Industries."
    )
    assert "Acme Corp" in result
    assert "Globex Industries" in result


def test_extract_entities_respects_max_entities(graph_no_driver):
    text = " ".join(f"Company{i} Corp" for i in range(20))
    result = graph_no_driver._extract_entity_candidates_from_text(text, max_entities=5)
    assert len(result) <= 5


def test_extract_entities_deduplicates(graph_no_driver):
    result = graph_no_driver._extract_entity_candidates_from_text(
        "Acme Corp is great. Acme Corp is really great."
    )
    assert result.count("Acme Corp") == 1


def test_extract_entities_domain_terms_optional_and_off_by_default(graph_no_driver):
    """A term that only matches via domain_terms shouldn't appear unless
    domain_terms is explicitly passed — no hardcoded vocabulary leaks in."""
    text = "we discussed radiation safety protocols today"
    without = graph_no_driver._extract_entity_candidates_from_text(text)
    assert not any("radiation" in e.lower() for e in without)

    with_terms = graph_no_driver._extract_entity_candidates_from_text(
        text, domain_terms=["radiation safety"]
    )
    assert any("radiation safety" in e.lower() for e in with_terms)


def test_extract_query_entities_delegates_correctly(graph_no_driver):
    result = graph_no_driver.extract_query_entities("What does Acme Corp do?")
    assert "Acme Corp" in result


# ---------------------------------------------------------------------------
# max_depth validation (the security fix — real Cypher-injection guard)
# ---------------------------------------------------------------------------

def test_max_depth_rejects_non_integer(graph_no_driver):
    with pytest.raises(ValueError):
        graph_no_driver.search_related_entities(["x"], max_depth="1; DROP")


def test_max_depth_rejects_too_large(graph_no_driver):
    with pytest.raises(ValueError):
        graph_no_driver.search_related_entities(["x"], max_depth=MAX_ALLOWED_DEPTH + 1)


def test_max_depth_rejects_zero_or_negative(graph_no_driver):
    with pytest.raises(ValueError):
        graph_no_driver.search_related_entities(["x"], max_depth=0)
    with pytest.raises(ValueError):
        graph_no_driver.search_related_entities(["x"], max_depth=-1)


def test_max_depth_accepts_valid_range(graph_no_driver):
    # driver is None, so this returns [] rather than raising — the point
    # here is only that validation itself doesn't reject valid input.
    result = graph_no_driver.search_related_entities(["x"], max_depth=3)
    assert result == []


# ---------------------------------------------------------------------------
# Driver-unavailable safety (every public method must degrade gracefully)
# ---------------------------------------------------------------------------

def test_health_check_false_without_driver(graph_no_driver):
    assert graph_no_driver.health_check() is False


def test_upsert_document_returns_error_without_driver(graph_no_driver):
    result = graph_no_driver.upsert_document(
        document_id="d1", title="t", chunks=[{"text": "Acme Corp"}]
    )
    assert result["success"] is False
    assert "not available" in result["error"]


def test_find_documents_empty_without_driver(graph_no_driver):
    assert graph_no_driver.find_documents_by_entities(["Acme Corp"]) == []


def test_document_entities_empty_without_driver(graph_no_driver):
    assert graph_no_driver.document_entities("doc-1") == []


def test_context_manager_closes_cleanly(graph_no_driver):
    with graph_no_driver as g:
        assert g is graph_no_driver


# ---------------------------------------------------------------------------
# Live integration test — real Neo4j, real round-trip, self-cleaning.
# ---------------------------------------------------------------------------

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
HAS_LIVE_NEO4J = bool(NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD)

TEST_NAMESPACE = "ragleap_graph_pytest"


@pytest.mark.skipif(not HAS_LIVE_NEO4J, reason="No live Neo4j credentials in environment")
def test_live_full_roundtrip():
    """
    Real end-to-end test against a real Neo4j instance: connect, write,
    query three ways, then clean up every node this test created —
    never leaves data behind in a real database.
    """
    config = GraphConfig(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    graph = GraphIndex(config=config)

    try:
        assert graph.health_check() is True

        result = graph.upsert_document(
            document_id="pytest-live-doc-1",
            title="Pytest Live Test Document",
            chunks=[{"text": "Acme Corp announced a partnership with Globex Industries."}],
            namespace=TEST_NAMESPACE,
        )
        assert result["success"] is True
        assert result["entities_indexed"] > 0

        docs = graph.find_documents_by_entities(["Acme Corp"], namespace=TEST_NAMESPACE)
        assert len(docs) == 1
        assert docs[0]["document_id"] == "pytest-live-doc-1"

        related = graph.search_related_entities(
            ["Acme Corp"], namespace=TEST_NAMESPACE, max_depth=2
        )
        assert any(r["entity_name"] == "Globex Industries" for r in related)

        entities = graph.document_entities("pytest-live-doc-1", namespace=TEST_NAMESPACE)
        entity_names = {e["entity_name"] for e in entities}
        assert "Acme Corp" in entity_names
        assert "Globex Industries" in entity_names

    finally:
        with graph.driver.session() as session:
            session.run(
                "MATCH (n) WHERE n.namespace = $ns DETACH DELETE n",
                ns=TEST_NAMESPACE,
            )
        graph.close()


# ---------------------------------------------------------------------------
# Entity typing (v0.5.0)
# ---------------------------------------------------------------------------

def test_collect_entities_for_chunk_regex_path_returns_unknown_type(graph_no_driver):
    """Regex extraction has no semantic understanding to draw a type
    from - every entity must be paired with 'UNKNOWN', not left
    untyped or crashing."""
    text = "Acme Corp reported strong Q3 revenue with ALARA compliance."
    result = graph_no_driver._collect_entities_for_chunk(text, max_entities=12, domain_terms=None)
    assert len(result) > 0
    assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in result)
    assert all(entity_type == "UNKNOWN" for _, entity_type in result)


def test_collect_entities_for_chunk_regex_path_names_match_old_behavior(graph_no_driver):
    """Regression guard: the set of entity NAMES extracted by the regex
    path must be identical before and after the (name, type) tuple
    change - only the return shape changed, not the extraction logic."""
    text = "Acme Corp reported strong Q3 revenue with ALARA compliance."
    old_style_names = graph_no_driver._extract_entity_candidates_from_text(text, max_entities=12)
    new_style_names = [name for name, _ in graph_no_driver._collect_entities_for_chunk(text, max_entities=12, domain_terms=None)]
    assert old_style_names == new_style_names


def test_find_entities_by_type_empty_without_driver(graph_no_driver):
    assert graph_no_driver.find_entities_by_type("ORG") == []


def test_find_entities_by_type_empty_string_returns_empty(graph_no_driver):
    assert graph_no_driver.find_entities_by_type("") == []
    assert graph_no_driver.find_entities_by_type("   ") == []
