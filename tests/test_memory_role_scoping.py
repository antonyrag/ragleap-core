"""
Tests for role-scoped memory retrieval (core/employees/memory.py +
core/employees/skills.py). Covers the fix for semantic_search() having
no tag filter at all -- previously any role's query could surface any
other role's stored memories via similarity search alone.
"""
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.employees import memory, skills
from core.employees.defaults import ROLE_SKILL_TAGS
from core.employees._db import get_connection

VEC_A = "[" + ",".join(["0.10"] * 3072) + "]"
VEC_B = "[" + ",".join(["0.11"] * 3072) + "]"


@pytest.fixture(autouse=True)
def clean_memory_table():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM employee_memory WHERE source = 'test_role_scoping'")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    yield


def _insert_row(text, tags, embedding_literal):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO employee_memory
                (text_content, summary, tags, importance, source, permanent,
                 review_after_days, content_hash, embedding, token_count)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
            """,
            (text, text[:300], json.dumps(tags), 0.7,
             "test_role_scoping", False, 180, text[:8], embedding_literal, len(text.split())),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def test_semantic_search_without_tags_returns_across_roles():
    """Baseline: with tags=None (the old default behavior), search is
    still unscoped -- this is intentional for any caller that genuinely
    wants a global search, and confirms we didn't accidentally remove
    that capability."""
    _insert_row("Sales pricing info", ["sales", "core"], VEC_A)
    _insert_row("Healthcare intake info", ["healthcare", "intake"], VEC_B)

    with patch("core.employees.memory.EmbeddingService") as MockService:
        MockService.return_value.embed_text.return_value = [0.10] * 3072
        results = memory.semantic_search("pricing", top_k=10)

    tags_seen = {t for r in results for t in r["tags"]}
    assert "sales" in tags_seen
    assert "healthcare" in tags_seen


def test_semantic_search_with_tags_excludes_other_roles():
    """The actual fix: passing tags restricts results to entries sharing
    at least one tag -- a healthcare-tagged memory must not leak into a
    sales-scoped search."""
    _insert_row("Sales pricing info", ["sales", "core"], VEC_A)
    _insert_row("Healthcare intake info", ["healthcare", "intake"], VEC_B)

    with patch("core.employees.memory.EmbeddingService") as MockService:
        MockService.return_value.embed_text.return_value = [0.10] * 3072
        results = memory.semantic_search("pricing", top_k=10, tags=["sales", "core"])

    tags_seen = {t for r in results for t in r["tags"]}
    assert "sales" in tags_seen
    assert "healthcare" not in tags_seen, "tag-scoped semantic search leaked another role's memory"


def test_get_role_skills_passes_role_tags_to_semantic_search():
    """skills.py's get_role_skills() must actually pass the role's own
    tags into semantic_search() -- the fix is useless if the only real
    caller never uses the new parameter."""
    with patch("core.employees.skills.memory") as mock_memory:
        mock_memory.get_owner_instructions.return_value = ""
        mock_memory.semantic_search.return_value = []
        mock_memory.tag_search.return_value = []
        mock_memory.format_context.return_value = ""
        skills.get_role_skills(role="healthcare_intake", query="what are your hours")
        _, kwargs = mock_memory.semantic_search.call_args
        assert kwargs.get("tags") == ROLE_SKILL_TAGS["healthcare_intake"]


def test_get_role_skills_with_ids_passes_role_tags_to_semantic_search():
    with patch("core.employees.skills.memory") as mock_memory:
        mock_memory.get_owner_instructions.return_value = ""
        mock_memory.semantic_search.return_value = []
        mock_memory.tag_search.return_value = []
        mock_memory.format_context.return_value = ""
        skills.get_role_skills_with_ids(role="legal_intake", query="what documents do I need")
        _, kwargs = mock_memory.semantic_search.call_args
        assert kwargs.get("tags") == ROLE_SKILL_TAGS["legal_intake"]
