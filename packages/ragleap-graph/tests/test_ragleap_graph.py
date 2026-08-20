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


def test_extract_query_entities_excludes_sentence_initial_stopwords(graph_no_driver):
    """Regression test: capitalized question words ("What", "Who", "The", ...)
    should not be extracted as entities just because English capitalizes the
    first word of a sentence. Documented as a known limitation prior to this
    fix - see CHANGELOG.
    """
    result = graph_no_driver.extract_query_entities("What did Acme Corp launch?")
    assert "Acme Corp" in result
    assert "What" not in result

    result2 = graph_no_driver.extract_query_entities("Who founded Acme Corp?")
    assert "Acme Corp" in result2
    assert "Who" not in result2


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

TEST_DATABASE_URL = os.environ.get(
    "RAGLEAP_TEST_DATABASE_URL",
    "postgresql://ragleap_test_user:ragleap_test_pass@127.0.0.1:5432/ragleap_test",
)

ollama_available = True
try:
    import requests
    requests.get("http://localhost:11434/api/tags", timeout=1).raise_for_status()
except Exception:
    ollama_available = False

psycopg2_available = True
try:
    import psycopg2  # noqa: F401
except ImportError:
    psycopg2_available = False

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


@pytest.mark.skipif(not HAS_LIVE_NEO4J, reason="No live Neo4j credentials in environment")
def test_upsert_document_contains_is_actually_idempotent():
    """
    Regression test for two real bugs found in upsert_document() (v0.5.4):
    1. Weight-doubling: re-upserting identical content doubled CONTAINS
       weight every time, contradicting the docstring's "idempotent -
       safe to re-run" claim.
    2. Stale entities: re-upserting a document whose content changed to
       no longer mention an entity left the old CONTAINS edge in place
       forever - never cleaned up.
    Scoped to CONTAINS only - CO_OCCURS_WITH/RELATES_AS still aggregate
    weight across multiple documents by design and are not covered by
    this fix (see the code comment at the fix site).
    """
    config = GraphConfig(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    graph = GraphIndex(config=config)
    try:
        graph.upsert_document(
            "idempotent-doc-1", "Test", [{"text": "Acme Corp is great."}],
            namespace=TEST_NAMESPACE,
        )
        graph.upsert_document(
            "idempotent-doc-1", "Test", [{"text": "Acme Corp is great."}],
            namespace=TEST_NAMESPACE,
        )
        with graph.driver.session() as session:
            row = session.run(
                "MATCH (:Document {id: $id, namespace: $ns})"
                "-[c:CONTAINS]->(:Entity {name: $name}) RETURN c.weight AS w",
                id="idempotent-doc-1", ns=TEST_NAMESPACE, name="acme corp",
            ).single()
            assert row["w"] == 1.0

        graph.upsert_document(
            "idempotent-doc-2", "Test2",
            [{"text": "Globex Corp announced results."}],
            namespace=TEST_NAMESPACE,
        )
        graph.upsert_document(
            "idempotent-doc-2", "Test2",
            [{"text": "No companies mentioned here now."}],
            namespace=TEST_NAMESPACE,
        )
        with graph.driver.session() as session:
            names = {
                row["name"] for row in session.run(
                    "MATCH (:Document {id: $id, namespace: $ns})"
                    "-[:CONTAINS]->(e:Entity) RETURN e.display_name AS name",
                    id="idempotent-doc-2", ns=TEST_NAMESPACE,
                )
            }
            assert "Globex Corp" not in names
    finally:
        with graph.driver.session() as session:
            session.run(
                "MATCH (n) WHERE n.namespace = $ns DETACH DELETE n",
                ns=TEST_NAMESPACE,
            )
        graph.close()


@pytest.mark.skipif(
    not (HAS_LIVE_NEO4J and ollama_available),
    reason="Needs both live Neo4j credentials and Ollama running on localhost:11434",
)
def test_relates_as_per_document_contribution_tracking():
    """
    Same idempotency fix as test_co_occurs_with_per_document_contribution_tracking,
    for RELATES_AS instead (v0.6.0). Uses real Ollama (qwen2.5:0.5b, same
    model this project's own benchmarks use for local inference) rather
    than Gemini, since this method requires a real LLM call for relation
    extraction and Ollama needs no API key.
    """
    from ragleap import ProviderConfig
    from ragleap_graph import ExtractionConfig

    provider = ProviderConfig(provider="ollama", model="qwen2.5:0.5b")
    extraction = ExtractionConfig(method="llm", provider=provider, extract_relations=True)
    config = GraphConfig(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    graph = GraphIndex(config=config, extraction=extraction)
    try:
        graph.upsert_document(
            "relates-doc-1", "Test",
            [{"text": "Acme Corp partnered with Globex Corp last year."}],
            namespace=TEST_NAMESPACE,
        )
        graph.upsert_document(
            "relates-doc-1", "Test",
            [{"text": "Acme Corp partnered with Globex Corp last year."}],
            namespace=TEST_NAMESPACE,
        )
        with graph.driver.session() as session:
            rows = session.run(
                "MATCH (:Entity)-[r:RELATES_AS]->(:Entity) "
                "WHERE r.relation_type IS NOT NULL "
                "RETURN r.relation_type AS rt, r.weight AS w"
            ).data()
            assert len(rows) >= 1, "expected at least one RELATES_AS edge from real extraction"
            assert all(row["w"] == 1.0 for row in rows), (
                f"weight should be 1.0 after identical re-upsert, got: {rows}"
            )
    finally:
        with graph.driver.session() as session:
            session.run(
                "MATCH (n) WHERE n.namespace = $ns DETACH DELETE n",
                ns=TEST_NAMESPACE,
            )
        graph.close()


@pytest.mark.skipif(not HAS_LIVE_NEO4J, reason="No live Neo4j credentials in environment")
def test_co_occurs_with_per_document_contribution_tracking():
    """
    Regression test for the same idempotency class of bug as CONTAINS
    (fixed in v0.5.4), now for CO_OCCURS_WITH (v0.6.0). Three real
    behaviors this proves, not just one:
    1. Re-upserting identical content does NOT double the weight
       (previously did - the actual bug).
    2. A genuinely different document sharing the same entity pair DOES
       correctly aggregate weight (proves the fix doesn't break the
       legitimate cross-document aggregation CO_OCCURS_WITH is for).
    3. Removing a document's contribution (re-upserting with content
       that no longer mentions the pair) correctly drops the aggregate
       weight, rather than leaving stale contribution behind.
    """
    config = GraphConfig(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    graph = GraphIndex(config=config)
    try:
        graph.upsert_document(
            "cooccur-doc-a", "Test",
            [{"text": "Acme Corp and Globex Corp are rivals."}],
            namespace=TEST_NAMESPACE,
        )
        graph.upsert_document(
            "cooccur-doc-a", "Test",
            [{"text": "Acme Corp and Globex Corp are rivals."}],
            namespace=TEST_NAMESPACE,
        )
        with graph.driver.session() as session:
            row = session.run(
                "MATCH (:Entity {name: $a})-[c:CO_OCCURS_WITH]-(:Entity {name: $b}) "
                "RETURN c.weight AS w",
                a="acme corp", b="globex corp",
            ).single()
            assert row["w"] == 1.0

        graph.upsert_document(
            "cooccur-doc-b", "Test2",
            [{"text": "Acme Corp and Globex Corp compete fiercely."}],
            namespace=TEST_NAMESPACE,
        )
        with graph.driver.session() as session:
            row = session.run(
                "MATCH (:Entity {name: $a})-[c:CO_OCCURS_WITH]-(:Entity {name: $b}) "
                "RETURN c.weight AS w",
                a="acme corp", b="globex corp",
            ).single()
            assert row["w"] == 2.0

        graph.upsert_document(
            "cooccur-doc-b", "Test2",
            [{"text": "Totally unrelated content now, no companies."}],
            namespace=TEST_NAMESPACE,
        )
        with graph.driver.session() as session:
            row = session.run(
                "MATCH (:Entity {name: $a})-[c:CO_OCCURS_WITH]-(:Entity {name: $b}) "
                "RETURN c.weight AS w",
                a="acme corp", b="globex corp",
            ).single()
            assert row["w"] == 1.0
    finally:
        with graph.driver.session() as session:
            session.run(
                "MATCH (n) WHERE n.namespace = $ns DETACH DELETE n",
                ns=TEST_NAMESPACE,
            )
        graph.close()


@pytest.mark.skipif(not HAS_LIVE_NEO4J, reason="No live Neo4j credentials in environment")
def test_find_entities_by_type_is_case_insensitive():
    """
    Regression test for a known limitation: find_entities_by_type()
    did exact-string-match only, so "Customer" and "customer" were
    treated as different types even though entity_type is stored
    exactly as the LLM (or "UNKNOWN") produced it, with no normalization
    applied at write time - a caller has no reliable way to predict the
    exact casing without already knowing it.
    """
    config = GraphConfig(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    graph = GraphIndex(config=config)
    try:
        with graph.driver.session() as session:
            session.run(
                "MERGE (e:Entity {name: $name, namespace: $ns}) "
                "SET e.display_name = $display, e.entity_type = $et",
                name="acme corp", ns=TEST_NAMESPACE, display="Acme Corp", et="Customer",
            )

        exact = graph.find_entities_by_type("Customer", namespace=TEST_NAMESPACE)
        assert len(exact) == 1

        lower = graph.find_entities_by_type("customer", namespace=TEST_NAMESPACE)
        assert len(lower) == 1

        upper = graph.find_entities_by_type("CUSTOMER", namespace=TEST_NAMESPACE)
        assert len(upper) == 1
    finally:
        with graph.driver.session() as session:
            session.run(
                "MATCH (n) WHERE n.namespace = $ns DETACH DELETE n",
                ns=TEST_NAMESPACE,
            )
        graph.close()


@pytest.mark.skipif(not HAS_LIVE_NEO4J, reason="No live Neo4j credentials in environment")
def test_find_relations_direction_parameter():
    """
    Regression test for find_relations(direction=) (v0.5.3). Known
    limitation prior to this fix: find_relations() only ever searched
    outgoing relations - "Globex Industries" would find nothing even
    though it's clearly the object of a real relation.

    Writes RELATES_AS edges directly via Cypher (bypassing LLM
    extraction, which find_relations() doesn't touch anyway) so this
    test is deterministic and only needs NEO4J_URI, not GEMINI_API_KEY.

    Graph: (Acme Corp)-[:PARTNERED_WITH]->(Globex Industries)
    """
    config = GraphConfig(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    graph = GraphIndex(config=config)
    try:
        with graph.driver.session() as session:
            session.run(
                """
                MERGE (a:Entity {name: $subj, namespace: $ns})
                ON CREATE SET a.display_name = $subj_display, a.entity_type = "UNKNOWN"
                MERGE (b:Entity {name: $obj, namespace: $ns})
                ON CREATE SET b.display_name = $obj_display, b.entity_type = "UNKNOWN"
                MERGE (a)-[r:RELATES_AS {relation_type: $rel}]->(b)
                SET r.weight = 1.0
                """,
                subj="acme corp", subj_display="Acme Corp",
                obj="globex industries", obj_display="Globex Industries",
                rel="PARTNERED_WITH",
                ns=TEST_NAMESPACE,
            )

        # Existing behavior (default direction="outgoing") - unchanged, must still work
        outgoing = graph.find_relations("Acme Corp", namespace=TEST_NAMESPACE)
        assert len(outgoing) == 1
        assert outgoing[0]["subject"] == "Acme Corp"
        assert outgoing[0]["object"] == "Globex Industries"

        # The actual bug: searching from the object side with default
        # direction finds nothing, even though Globex Industries is
        # clearly involved in a real relation.
        outgoing_from_object = graph.find_relations("Globex Industries", namespace=TEST_NAMESPACE)
        assert outgoing_from_object == []

        # New: direction="incoming" - the fix
        incoming = graph.find_relations(
            "Globex Industries", namespace=TEST_NAMESPACE, direction="incoming"
        )
        assert len(incoming) == 1
        assert incoming[0]["subject"] == "Acme Corp"
        assert incoming[0]["object"] == "Globex Industries"

        # New: direction="both" finds the relation from either side
        both_from_subject = graph.find_relations(
            "Acme Corp", namespace=TEST_NAMESPACE, direction="both"
        )
        assert len(both_from_subject) == 1
        both_from_object = graph.find_relations(
            "Globex Industries", namespace=TEST_NAMESPACE, direction="both"
        )
        assert len(both_from_object) == 1

        # Invalid direction value should raise, not silently misbehave
        with pytest.raises(ValueError):
            graph.find_relations("Acme Corp", namespace=TEST_NAMESPACE, direction="sideways")
    finally:
        with graph.driver.session() as session:
            session.run(
                "MATCH (n) WHERE n.namespace = $ns DETACH DELETE n",
                ns=TEST_NAMESPACE,
            )
        graph.close()


@pytest.mark.skipif(not HAS_LIVE_NEO4J, reason="No live Neo4j credentials in environment")
def test_backfill_user_id_defaults_prevents_duplicate_entities_on_reupsert():
    """
    Regression test for backfill_user_id_defaults() (v0.6.5). All read
    methods now use coalesce(node.user_id, '') = $user_id, so legacy
    data (no user_id property) is correctly visible without needing
    migration first - that half of the original concern is already
    handled structurally.
    The real remaining bug is in upsert_document()'s WRITE path:
    Entity MERGE now keys on (name, namespace, user_id) by design (the
    deliberate split-identity model), so a node written before user_id=
    existed has no user_id property and will NOT match the MERGE
    pattern used by the current code. Re-upserting an already-indexed
    document therefore creates a DUPLICATE Entity node instead of
    updating the existing one - this is the actual data-fragmentation
    risk backfill_user_id_defaults() exists to prevent.
    Writes a legacy-style Entity node directly via Cypher (no user_id
    property, simulating real pre-upgrade data), then calls the real
    upsert_document() to prove duplication happens, then confirms that
    running the migration stops further duplicate growth on subsequent
    re-upserts.
    """
    config = GraphConfig(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    graph = GraphIndex(config=config)
    doc_id = "legacy-doc-1"
    entity_name = "legacy widgets inc"
    try:
        with graph.driver.session() as session:
            session.run(
                """
                MERGE (e:Entity {name: $name, namespace: $ns})
                ON CREATE SET e.display_name = $display, e.entity_type = "UNKNOWN"
                """,
                name=entity_name, display="Legacy Widgets Inc",
                ns=TEST_NAMESPACE,
            )

        def count_entities():
            with graph.driver.session() as session:
                result = session.run(
                    "MATCH (e:Entity {name: $name, namespace: $ns}) RETURN count(e) AS c",
                    name=entity_name, ns=TEST_NAMESPACE,
                )
                return result.single()["c"]

        assert count_entities() == 1

        summary = graph.upsert_document(
            document_id=doc_id,
            title="Legacy Widgets Inc report",
            chunks=[{"text": "Legacy Widgets Inc announced new products today."}],
            namespace=TEST_NAMESPACE,
        )
        assert summary["success"] is True

        assert count_entities() == 2, (
            "Expected the duplication bug to reproduce: re-upserting "
            "should have created a second Entity node distinct from "
            "the pre-existing legacy one, since MERGE now keys on "
            "user_id and the legacy node has no user_id property"
        )

        counts = graph.backfill_user_id_defaults(namespace=TEST_NAMESPACE)
        assert counts["Entity"] >= 1

        summary2 = graph.upsert_document(
            document_id=doc_id,
            title="Legacy Widgets Inc report",
            chunks=[{"text": "Legacy Widgets Inc announced new products today."}],
            namespace=TEST_NAMESPACE,
        )
        assert summary2["success"] is True
        assert count_entities() == 2, (
            "After backfill, re-upserting should no longer create "
            "further duplicates - count must stay stable, not grow"
        )
    finally:
        with graph.driver.session() as session:
            session.run(
                "MATCH (n) WHERE n.namespace = $ns DETACH DELETE n",
                ns=TEST_NAMESPACE,
            )
        graph.close()


@pytest.mark.skipif(not HAS_LIVE_NEO4J, reason="No live Neo4j credentials in environment")
def test_find_lineage():
    """
    Regression test for find_lineage() (v0.6.4). Previously the
    PairWeight/RelationWeight tracking nodes introduced in v0.6.0 for
    idempotent weight aggregation had no public read path - this test
    proves find_lineage() actually surfaces them correctly.
    Writes PairWeight/RelationWeight nodes directly via Cypher (bypassing
    upsert_document(), which find_lineage() doesn't touch anyway) so this
    test is deterministic and only needs NEO4J_URI.
    Simulates two documents both mentioning (Acme Corp, Globex Industries)
    with a CO_OCCURS_WITH signal, plus one document asserting a
    RELATES_AS PARTNERED_WITH relation between the same pair.
    """
    config = GraphConfig(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    graph = GraphIndex(config=config)
    try:
        with graph.driver.session() as session:
            session.run(
                """
                MERGE (pw:PairWeight {namespace: $ns, document_id: $doc1, entity_a: $a, entity_b: $b})
                SET pw.weight = $w1
                """,
                ns=TEST_NAMESPACE, doc1="doc-1", a="acme corp", b="globex industries", w1=0.6,
            )
            session.run(
                """
                MERGE (pw:PairWeight {namespace: $ns, document_id: $doc2, entity_a: $a, entity_b: $b})
                SET pw.weight = $w2
                """,
                ns=TEST_NAMESPACE, doc2="doc-2", a="acme corp", b="globex industries", w2=0.4,
            )
            session.run(
                """
                MERGE (rw:RelationWeight {namespace: $ns, document_id: $doc3, subject: $subj, relation_type: $rel, object: $obj})
                SET rw.weight = $w3
                """,
                ns=TEST_NAMESPACE, doc3="doc-3", subj="acme corp", rel="PARTNERED_WITH", obj="globex industries", w3=1.0,
            )

        results = graph.find_lineage("Acme Corp", "Globex Industries", namespace=TEST_NAMESPACE)
        assert len(results) == 3
        co_occurs = [r for r in results if r["relation_type"] == "CO_OCCURS_WITH"]
        relates = [r for r in results if r["relation_type"] == "RELATES_AS"]
        assert len(co_occurs) == 2
        assert {r["document_id"] for r in co_occurs} == {"doc-1", "doc-2"}
        assert {r["weight"] for r in co_occurs} == {0.6, 0.4}
        assert len(relates) == 1
        assert relates[0]["document_id"] == "doc-3"
        assert relates[0]["relation_name"] == "PARTNERED_WITH"
        assert relates[0]["weight"] == 1.0

        swapped = graph.find_lineage("Globex Industries", "Acme Corp", namespace=TEST_NAMESPACE)
        assert len(swapped) == 3
        assert {r["document_id"] for r in swapped} == {"doc-1", "doc-2", "doc-3"}

        filtered_out = graph.find_lineage(
            "Acme Corp", "Globex Industries", namespace=TEST_NAMESPACE, relation_type="SOMETHING_ELSE"
        )
        assert len(filtered_out) == 2
        assert all(r["relation_type"] == "CO_OCCURS_WITH" for r in filtered_out)

        filtered_match = graph.find_lineage(
            "Acme Corp", "Globex Industries", namespace=TEST_NAMESPACE, relation_type="PARTNERED_WITH"
        )
        assert len(filtered_match) == 3

        empty = graph.find_lineage("Acme Corp", "Nonexistent Entity", namespace=TEST_NAMESPACE)
        assert empty == []
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


@pytest.mark.skipif(
    not (HAS_LIVE_NEO4J and psycopg2_available),
    reason="No live Neo4j credentials, or psycopg2 not installed (pip install ragleap-graph[audit])",
)
def test_audit_logging_records_every_wired_method():
    """
    Regression test for audit logging (v0.6.6). Live-verifies against
    real Postgres AND real Neo4j - not a mock - that all 7 audit-wired
    methods (upsert_document + 6 read methods) each produce exactly one
    correctly-tagged row in ragleap_graph_audit_log.
    Uses a unique namespace/user_id pair so this test's rows are
    trivially distinguishable from anything else that may exist in the
    shared test database, and cleans up both Postgres and Neo4j state
    in the finally block regardless of outcome.
    """
    import psycopg2

    from ragleap_graph import GraphConfig, GraphIndex
    from ragleap_graph._audit import AuditConfig

    audit_ns = "__audit_test_ns__"
    audit_uid = "audit_test_user"
    doc_id = "audit-test-doc-1"

    config = GraphConfig(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    audit = AuditConfig(database_url=TEST_DATABASE_URL)
    graph = GraphIndex(config=config, audit=audit)

    try:
        summary = graph.upsert_document(
            document_id=doc_id,
            title="Audit Test",
            chunks=[{"text": "Audit Test Corp announced new products today."}],
            namespace=audit_ns,
            user_id=audit_uid,
        )
        assert summary["success"] is True

        graph.find_relations("Audit Test Corp", namespace=audit_ns, user_id=audit_uid)
        graph.find_documents_by_entities(["Audit Test Corp"], namespace=audit_ns, user_id=audit_uid)
        graph.document_entities(doc_id, namespace=audit_ns, user_id=audit_uid)
        graph.find_entities_by_type("UNKNOWN", namespace=audit_ns, user_id=audit_uid)
        graph.find_lineage("Audit Test Corp", "Nonexistent Entity", namespace=audit_ns, user_id=audit_uid)
        graph.search_related_entities(["Audit Test Corp"], namespace=audit_ns, user_id=audit_uid)

        pg_conn = psycopg2.connect(TEST_DATABASE_URL)
        try:
            with pg_conn.cursor() as cur:
                cur.execute(
                    "SELECT action, user_id, namespace FROM ragleap_graph_audit_log "
                    "WHERE namespace = %s ORDER BY id",
                    (audit_ns,),
                )
                rows = cur.fetchall()
        finally:
            pg_conn.close()

        actions = [r[0] for r in rows]
        expected_actions = [
            "upsert_document",
            "find_relations",
            "find_documents_by_entities",
            "document_entities",
            "find_entities_by_type",
            "find_lineage",
            "search_related_entities",
        ]
        assert actions == expected_actions, f"Expected {expected_actions}, got {actions}"
        assert all(r[1] == audit_uid for r in rows)
        assert all(r[2] == audit_ns for r in rows)
    finally:
        with graph.driver.session() as session:
            session.run(
                "MATCH (n) WHERE n.namespace = $ns DETACH DELETE n",
                ns=audit_ns,
            )
        graph.close()
        try:
            pg_conn = psycopg2.connect(TEST_DATABASE_URL)
            with pg_conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ragleap_graph_audit_log WHERE namespace = %s",
                    (audit_ns,),
                )
            pg_conn.commit()
            pg_conn.close()
        except Exception:
            pass
