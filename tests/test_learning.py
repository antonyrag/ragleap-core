"""
Tests for core/employees/learning.py's learn_from_owner_approval() -
records the owner's real approve/reject decision as a learned skill,
distinctly for each outcome (not mislabeling a rejection as an
approval). write_learned_skill is mocked, no live DB/API needed.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.employees import learning


def test_approved_action_recorded_as_approved():
    with patch.object(learning.memory, "write_learned_skill") as mock_write:
        learning.learn_from_owner_approval("send_email", "Send invoice to client", "sent OK", approved=True)
    assert mock_write.call_count == 1
    _, kwargs = mock_write.call_args
    assert "OWNER APPROVED ACTION" in kwargs["text"]
    assert "owner_approved" in kwargs["tags"]
    assert "owner_rejected" not in kwargs["tags"]
    assert kwargs["source"] == "owner_approval"


def test_rejected_action_recorded_as_rejected_not_approved():
    with patch.object(learning.memory, "write_learned_skill") as mock_write:
        learning.learn_from_owner_approval("send_email", "Send invoice to client", "REJECTED by owner", approved=False)
    assert mock_write.call_count == 1
    _, kwargs = mock_write.call_args
    assert "OWNER REJECTED ACTION" in kwargs["text"]
    assert "OWNER APPROVED ACTION" not in kwargs["text"]
    assert "owner_rejected" in kwargs["tags"]
    assert "owner_approved" not in kwargs["tags"]


def test_default_approved_true_for_backward_compatibility():
    """approved defaults to True so any other/future caller that
    doesn't pass it keeps the original approved-only behavior."""
    with patch.object(learning.memory, "write_learned_skill") as mock_write:
        learning.learn_from_owner_approval("send_email", "detail", "outcome")
    _, kwargs = mock_write.call_args
    assert "OWNER APPROVED ACTION" in kwargs["text"]


def test_action_type_included_in_tags_for_both_outcomes():
    with patch.object(learning.memory, "write_learned_skill") as mock_write:
        learning.learn_from_owner_approval("post_to_slack", "detail", "outcome", approved=True)
    _, kwargs = mock_write.call_args
    assert "post_to_slack" in kwargs["tags"]

    with patch.object(learning.memory, "write_learned_skill") as mock_write:
        learning.learn_from_owner_approval("post_to_slack", "detail", "outcome", approved=False)
    _, kwargs = mock_write.call_args
    assert "post_to_slack" in kwargs["tags"]
