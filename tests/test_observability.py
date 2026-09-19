"""
Tests for core/observability.py - item #2 of the 9-pattern
agentic-architecture build (agent_traces table).
Requires a Postgres DB with db/schema.sql applied, reachable via the
DATABASE_URL env var (same convention as tests/test_autonomy.py).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import observability
from core.employees._db import get_connection


@pytest.fixture(autouse=True)
def clean_agent_traces():
    """Reset agent_traces before each test so tests do not interfere."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM agent_traces")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    yield


def _fetch_all_traces():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, query, detected_language, chunks_retrieved, chunks_sent, "
            "provider_used, fallback_used, prompt_tokens, completion_tokens, "
            "total_tokens, latency_ms, error, reflection_concern FROM agent_traces ORDER BY id"
        )
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()


def test_record_trace_inserts_a_row():
    ok = observability.record_trace(
        query="what is the refund policy?", role="support",
        detected_language="en", chunks_retrieved=5, chunks_sent=4,
        provider_used="gemini", fallback_used=False,
        prompt_tokens=100, completion_tokens=30, total_tokens=130,
        latency_ms=850,
    )
    assert ok is True

    rows = _fetch_all_traces()
    assert len(rows) == 1
    role, query, lang, retrieved, sent, provider, fallback, ptok, ctok, ttok, latency, error, reflection_concern = rows[0]
    assert role == "support"
    assert query == "what is the refund policy?"
    assert lang == "en"
    assert retrieved == 5
    assert sent == 4
    assert provider == "gemini"
    assert fallback is False
    assert ptok == 100
    assert ctok == 30
    assert ttok == 130
    assert latency == 850
    assert error is None
    assert reflection_concern is None


def test_record_trace_with_no_role_and_an_error():
    ok = observability.record_trace(query="hello", error="embedding failed", latency_ms=12)
    assert ok is True

    rows = _fetch_all_traces()
    assert len(rows) == 1
    role, query, *_rest, error, reflection_concern = rows[0]
    assert role is None
    assert query == "hello"
    assert error == "embedding failed"
    assert reflection_concern is None


def test_record_trace_with_reflection_concern():
    ok = observability.record_trace(
        query="do I have a case?", role="legal_intake", provider_used="gemini",
        reflection_concern="legal conclusion not present in source docs", latency_ms=900,
    )
    assert ok is True

    rows = _fetch_all_traces()
    assert len(rows) == 1
    role, query, *_rest, error, reflection_concern = rows[0]
    assert role == "legal_intake"
    assert error is None
    assert reflection_concern == "legal conclusion not present in source docs"


def test_record_trace_never_raises_on_bad_connection(monkeypatch):
    """record_trace() must be best-effort - a DB failure should never
    propagate and break the actual chat response."""
    def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(observability, "get_connection", _boom)
    ok = observability.record_trace(query="test")
    assert ok is False  # no exception raised


def test_report_with_no_traces_today():
    report = observability.generate_observability_report()
    assert "No traced requests today" in report


def test_report_aggregates_role_provider_and_error_rate():
    observability.record_trace(query="q1", role="support", provider_used="gemini", fallback_used=False, latency_ms=500)
    observability.record_trace(query="q2", role="support", provider_used="gemini", fallback_used=True, latency_ms=700)
    observability.record_trace(query="q3", role="sales", provider_used="groq", error="all providers failed", latency_ms=200)

    report = observability.generate_observability_report()
    assert "Total traced requests: 3" in report
    assert "Errors: 1" in report
    assert "Fallback provider used: 1" in report
    assert "support: 2" in report
    assert "sales: 1" in report
    assert "gemini: 2" in report
    assert "groq: 1" in report
    assert "Flagged by self-correction check" not in report  # none of these had a concern


def test_report_shows_reflection_flagged_count():
    observability.record_trace(query="q1", role="legal_intake", provider_used="gemini", latency_ms=500)
    observability.record_trace(
        query="q2", role="legal_intake", provider_used="gemini",
        reflection_concern="unsupported claim", latency_ms=600,
    )

    report = observability.generate_observability_report()
    assert "Flagged by self-correction check (item #3): 1" in report


def test_record_trace_reasoning_round_trips():
    from core.employees._db import get_connection
    q = "reasoning-roundtrip-test-query"
    assert observability.record_trace(query=q, role="legal_intake", reasoning="because of X and Y", latency_ms=5)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT reasoning FROM agent_traces WHERE query = %s ORDER BY id DESC LIMIT 1", (q,))
        row = cur.fetchone()
        cur.execute("DELETE FROM agent_traces WHERE query = %s", (q,))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    assert row[0] == "because of X and Y"
