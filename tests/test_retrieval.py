"""
Tests for core/retrieval.py's search_similar_chunks_with_graph() - direct
vs. indirect (1-2 hop) knowledge-graph boosting (Issue #25).

No DB or live Neo4j required - search_similar_chunks (vector search) and
graph_service's methods are mocked directly, so this tests only the
boost-selection logic in isolation.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.retrieval import VectorRetrievalService


def _make_service():
    return VectorRetrievalService()


def _candidate(chunk_id, document_id, score=0.5):
    return {
        "chunk_id": chunk_id,
        "text": f"text for {chunk_id}",
        "similarity_score": score,
        "document_id": document_id,
        "document_name": f"doc-{document_id}",
        "chunk_index": 0,
    }


def test_direct_match_gets_graph_boost():
    service = _make_service()
    candidates = [_candidate("c1", "doc-A", score=0.5)]

    with patch.object(service, "search_similar_chunks", return_value=candidates), \
         patch("core.retrieval.graph_service.extract_query_entities", return_value=["Neo4j"]), \
         patch("core.retrieval.graph_service.find_documents_by_entities", return_value=[{"document_id": "doc-A"}]), \
         patch("core.retrieval.graph_service.search_related_entities", return_value=[]):
        result = service.search_similar_chunks_with_graph("Tell me about Neo4j", [0.1], top_k=5)

    assert result[0]["document_id"] == "doc-A"
    assert result[0]["similarity_score"] == 0.65  # 0.5 + graph_boost (0.15)
    assert result[0]["graph_boosted"] is True
    assert "graph_boost_type" not in result[0]


def test_one_hop_indirect_match_gets_smaller_boost():
    """Neo4j -> PostgreSQL (1 hop). Doc mentions PostgreSQL, not Neo4j."""
    service = _make_service()
    candidates = [_candidate("c1", "doc-B", score=0.5)]

    with patch.object(service, "search_similar_chunks", return_value=candidates), \
         patch("core.retrieval.graph_service.extract_query_entities", return_value=["Neo4j"]), \
         patch("core.retrieval.graph_service.find_documents_by_entities") as mock_find, \
         patch("core.retrieval.graph_service.search_related_entities", return_value=[
             {"entity_name": "PostgreSQL", "name": "PostgreSQL", "relationship": "RELATED_TO", "depth": 1},
         ]):
        mock_find.side_effect = [
            [],                              # direct lookup: no match
            [{"document_id": "doc-B"}],       # indirect lookup: finds doc-B
        ]
        result = service.search_similar_chunks_with_graph("Tell me about Neo4j", [0.1], top_k=5)

    assert result[0]["document_id"] == "doc-B"
    assert result[0]["similarity_score"] == 0.75  # 0.5 + indirect_graph_boost (0.25)
    assert result[0]["graph_boosted"] is True
    assert result[0]["graph_boost_type"] == "indirect"


def test_two_hop_indirect_match_gets_smaller_boost():
    """Neo4j -> PostgreSQL -> Docker (2 hops). Doc mentions Docker only."""
    service = _make_service()
    candidates = [_candidate("c1", "doc-C", score=0.4)]

    with patch.object(service, "search_similar_chunks", return_value=candidates), \
         patch("core.retrieval.graph_service.extract_query_entities", return_value=["Neo4j"]), \
         patch("core.retrieval.graph_service.find_documents_by_entities") as mock_find, \
         patch("core.retrieval.graph_service.search_related_entities", return_value=[
             {"entity_name": "PostgreSQL", "name": "PostgreSQL", "relationship": "RELATED_TO", "depth": 1},
             {"entity_name": "Docker", "name": "Docker", "relationship": "RELATED_TO", "depth": 2},
         ]):
        mock_find.side_effect = [
            [],
            [{"document_id": "doc-C"}],
        ]
        result = service.search_similar_chunks_with_graph("Tell me about Neo4j", [0.1], top_k=5)

    assert result[0]["document_id"] == "doc-C"
    assert result[0]["similarity_score"] == 0.65  # 0.4 + indirect_graph_boost (0.25)
    assert result[0]["graph_boosted"] is True
    assert result[0]["graph_boost_type"] == "indirect"


def test_direct_match_wins_over_indirect_for_same_document():
    """A doc that is BOTH a direct match and reachable via related entities
    should only get the (larger) direct boost, not both stacked."""
    service = _make_service()
    candidates = [_candidate("c1", "doc-A", score=0.5)]

    with patch.object(service, "search_similar_chunks", return_value=candidates), \
         patch("core.retrieval.graph_service.extract_query_entities", return_value=["Neo4j"]), \
         patch("core.retrieval.graph_service.find_documents_by_entities") as mock_find, \
         patch("core.retrieval.graph_service.search_related_entities", return_value=[
             {"entity_name": "PostgreSQL", "name": "PostgreSQL", "relationship": "RELATED_TO", "depth": 1},
         ]):
        mock_find.side_effect = [
            [{"document_id": "doc-A"}],  # direct match
            [{"document_id": "doc-A"}],  # also indirectly reachable
        ]
        result = service.search_similar_chunks_with_graph("Tell me about Neo4j", [0.1], top_k=5)

    assert result[0]["similarity_score"] == 0.65  # direct boost only, not 0.5+0.15+0.25
    assert "graph_boost_type" not in result[0]


def test_no_related_entities_falls_back_to_direct_only():
    service = _make_service()
    candidates = [_candidate("c1", "doc-A", score=0.5)]

    with patch.object(service, "search_similar_chunks", return_value=candidates), \
         patch("core.retrieval.graph_service.extract_query_entities", return_value=["Neo4j"]), \
         patch("core.retrieval.graph_service.find_documents_by_entities", return_value=[{"document_id": "doc-A"}]), \
         patch("core.retrieval.graph_service.search_related_entities", return_value=[]):
        result = service.search_similar_chunks_with_graph("Tell me about Neo4j", [0.1], top_k=5)

    assert result[0]["similarity_score"] == 0.65
    assert "graph_boost_type" not in result[0]


def test_graph_failure_falls_back_to_pure_vector_results():
    """If graph_service raises (e.g. Neo4j unreachable), return unboosted
    vector results rather than crashing."""
    service = _make_service()
    candidates = [_candidate("c1", "doc-A", score=0.5)]

    with patch.object(service, "search_similar_chunks", return_value=candidates), \
         patch("core.retrieval.graph_service.extract_query_entities", side_effect=RuntimeError("neo4j down")):
        result = service.search_similar_chunks_with_graph("Tell me about Neo4j", [0.1], top_k=5)

    assert result[0]["document_id"] == "doc-A"
    assert result[0]["similarity_score"] == 0.5  # unchanged
    assert "graph_boosted" not in result[0]


def test_no_vector_candidates_returns_empty_without_graph_calls():
    service = _make_service()
    with patch.object(service, "search_similar_chunks", return_value=[]), \
         patch("core.retrieval.graph_service.extract_query_entities") as mock_entities:
        result = service.search_similar_chunks_with_graph("anything", [0.1], top_k=5)

    assert result == []
    mock_entities.assert_not_called()