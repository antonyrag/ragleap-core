"""
Tests for core/autonomy.py's rejection-pattern reporting (item #2 from
the pending list, deliberately scoped to real-data-only reporting - see
suggest_autonomy_changes()'s docstring for why the actual
pattern-suggestion logic isn't implemented yet).
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test")
from core import autonomy


def _mock_connection(rows):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = rows
    conn.cursor.return_value = cur
    return conn


def test_rejection_report_handles_no_rejections():
    with patch.object(autonomy, "get_connection", return_value=_mock_connection([])):
        report = autonomy.generate_rejection_pattern_report()
    assert "No rejections recorded yet" in report


def test_rejection_report_groups_and_counts_correctly():
    rows = [
        ("reply", "email", "sales"),
        ("reply", "email", "sales"),
        ("post", "telegram", "marketing"),
        ("reply", "email", "sales"),
    ]
    with patch.object(autonomy, "get_connection", return_value=_mock_connection(rows)):
        report = autonomy.generate_rejection_pattern_report()

    assert "Total rejections: 4" in report
    assert "reply via email (role: sales): 3 rejection(s)" in report
    assert "post via telegram (role: marketing): 1 rejection(s)" in report
    assert report.index("reply via email") < report.index("post via telegram")


def test_rejection_report_handles_null_role():
    rows = [("escalate_to_owner", "telegram", None)]
    with patch.object(autonomy, "get_connection", return_value=_mock_connection(rows)):
        report = autonomy.generate_rejection_pattern_report()
    assert "(role: (no role))" in report


def test_rejection_report_handles_db_error_gracefully():
    conn = MagicMock()
    conn.cursor.side_effect = Exception("connection lost")
    with patch.object(autonomy, "get_connection", return_value=conn):
        report = autonomy.generate_rejection_pattern_report()
    assert "error" in report.lower()


def test_suggest_autonomy_changes_is_explicitly_not_implemented():
    import pytest
    with pytest.raises(NotImplementedError, match="real rejection volume"):
        autonomy.suggest_autonomy_changes()


def test_min_rejections_threshold_reads_from_env_with_sane_default():
    assert autonomy.MIN_REJECTIONS_FOR_PATTERN_SUGGESTIONS == 25
