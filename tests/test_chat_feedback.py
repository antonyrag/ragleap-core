"""
Tests for core/api.py's /chat/feedback endpoint (chat_feedback function
called directly, not via HTTP/TestClient - it's a plain function under
the @app.post decorator). Covers the new optional channel/user_message/
ai_reply fields that additionally record a learned skill via
learn_from_conversation, on top of the existing reinforce-only
behavior via record_role_memory_outcome. employee_learning is mocked,
no live DB/API needed.

Requires DATABASE_URL to be set before import (core/api.py's module-
level setup needs it), even though these tests themselves don't touch
the DB - see the DATABASE_URL default below.
"""
import os
import sys
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://ragleap:ragleap@localhost:5433/ragleap_core")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.api import chat_feedback, MemoryFeedbackRequest, employee_learning


def test_feedback_without_conversation_fields_only_reinforces():
    """Backward compatibility: existing callers that only send
    role_memory_ids/success get the original reinforce-only behavior -
    learn_from_conversation must NOT be called."""
    req = MemoryFeedbackRequest(role_memory_ids=["abc-123"], success=True)
    with patch.object(employee_learning, "record_role_memory_outcome", return_value=1) as mock_reinforce, \
         patch.object(employee_learning, "learn_from_conversation") as mock_learn:
        result = chat_feedback(req)
    assert result == {"updated": 1}
    mock_reinforce.assert_called_once_with(["abc-123"], success=True)
    mock_learn.assert_not_called()


def test_feedback_with_conversation_fields_also_learns():
    req = MemoryFeedbackRequest(
        role_memory_ids=["abc-123"], success=True,
        channel="whatsapp", user_message="What are your hours?",
        ai_reply="We're open 9-5 Mon-Fri.",
    )
    with patch.object(employee_learning, "record_role_memory_outcome", return_value=1), \
         patch.object(employee_learning, "learn_from_conversation") as mock_learn:
        chat_feedback(req)
    mock_learn.assert_called_once_with(
        "whatsapp", "What are your hours?", "We're open 9-5 Mon-Fri.",
        resolved=True, score=0.85,
    )


def test_feedback_failure_still_calls_learn_with_resolved_false():
    """A failed outcome still calls learn_from_conversation (with
    resolved=False) rather than skipping it - learn_from_conversation's
    own internal guard (resolved and score>=0.5) is what decides
    whether anything actually gets written, not the endpoint."""
    req = MemoryFeedbackRequest(
        role_memory_ids=["abc-123"], success=False,
        channel="email", user_message="Can you process my refund?",
        ai_reply="I'm not able to help with that.",
    )
    with patch.object(employee_learning, "record_role_memory_outcome", return_value=0), \
         patch.object(employee_learning, "learn_from_conversation") as mock_learn:
        chat_feedback(req)
    mock_learn.assert_called_once_with(
        "email", "Can you process my refund?", "I'm not able to help with that.",
        resolved=False, score=0.3,
    )


def test_feedback_partial_conversation_fields_skips_learning():
    """All three of channel/user_message/ai_reply are required together -
    a partial set (e.g. only channel) should NOT trigger a call, since
    learn_from_conversation needs all three to write meaningful text."""
    req = MemoryFeedbackRequest(
        role_memory_ids=["abc-123"], success=True, channel="whatsapp",
    )
    with patch.object(employee_learning, "record_role_memory_outcome", return_value=1), \
         patch.object(employee_learning, "learn_from_conversation") as mock_learn:
        chat_feedback(req)
    mock_learn.assert_not_called()
