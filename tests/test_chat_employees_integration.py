"""
Tests for /chat role wiring (issue #134): _build_system_prompt,
_augment_query_with_reminder, and the ask() integration of both.

No real DB, embedding, or LLM calls — all collaborators are patched.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import budget, chat
from core.employees import skills as employee_skills
from core.employees import memory as employee_memory
from core.employees.defaults import DEFAULT_ROLES


@pytest.fixture(autouse=True)
def _reset_budget_role():
    """chat.ask() sets a process-wide budget role ContextVar and never clears it.

    Left set, the last role asked for here leaks into later tests: they write it
    into the usage ledger (core/budget.record_usage reads the same ContextVar),
    and tests that assert on the ledger's roles then fail
    (tests/test_office_org.py::test_org_chart_grouping_fields_and_open_task_counts).
    """
    yield
    budget.set_role(None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_generation(return_value):
    mock_instance = MagicMock()
    mock_instance.generate_answer.return_value = return_value
    mock_class = MagicMock(return_value=mock_instance)
    return mock_class


def _run_ask(query, role=None, system_prompt=None, chunks=None, owner_instructions=""):
    """Run chat.ask() with all external dependencies mocked out.
    Returns (result_dict, mock_trace) so tests can inspect both.
    """
    if chunks is None:
        chunks = [{"document_name": "doc1", "text": "chunk text"}]

    mock_gen = _mock_generation({
        "answer": "test answer",
        "sources": ["doc1"],
        "provider_used": "gemini",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        "chunks_sent": len(chunks),
        "fallback_used": False,
    })

    with patch.object(chat, "_prepare", return_value=(chunks, "en", False)), \
         patch.object(chat, "GenerationService", mock_gen), \
         patch.object(chat, "record_trace") as mock_trace, \
         patch.object(employee_memory, "get_owner_instructions", return_value=owner_instructions):
        result = chat.ask(query, role=role, system_prompt=system_prompt)

    return result, mock_trace


# ---------------------------------------------------------------------------
# 1. ask() without role — no role context injected
# ---------------------------------------------------------------------------

def test_ask_without_role_no_role_context():
    """Without role, _build_system_prompt returns (base_system_prompt, [])
    and _augment_query_with_reminder returns the query unchanged.
    """
    base_prompt = "Base system prompt"
    result, mock_trace = _run_ask(
        "what is the refund policy?",
        role=None,
        system_prompt=base_prompt,
    )

    assert result["answer"] == "test answer"
    # Verify _build_system_prompt was called with role=None
    # (we can't easily inspect internal calls without more patching,
    # but we can verify the trace recorded role=None)
    kwargs = mock_trace.call_args.kwargs
    assert kwargs["role"] is None


def test_ask_without_role_system_prompt_passthrough():
    """Without role, the system_prompt passed to generate_answer is exactly
    the base_system_prompt (no augmentation).
    """
    base_prompt = "Custom base prompt"
    chunks = [{"document_name": "doc1", "text": "chunk"}]

    mock_gen = _mock_generation({
        "answer": "answer", "sources": [], "provider_used": "gemini",
        "usage": None, "chunks_sent": 1, "fallback_used": False,
    })

    with patch.object(chat, "_prepare", return_value=(chunks, "en", False)), \
         patch.object(chat, "GenerationService", mock_gen), \
         patch.object(chat, "record_trace"), \
         patch.object(employee_memory, "get_owner_instructions", return_value=""):
        chat.ask("question", role=None, system_prompt=base_prompt)

    # Inspect what generate_answer received
    gen_instance = mock_gen.return_value
    call_kwargs = gen_instance.generate_answer.call_args
    # system_prompt kwarg should be exactly base_prompt
    assert call_kwargs.kwargs.get("system_prompt") == base_prompt or \
           (call_kwargs.args[2] if len(call_kwargs.args) > 2 else call_kwargs.kwargs.get("system_prompt")) == base_prompt


# ---------------------------------------------------------------------------
# 2. ask() with valid role — personality and role context injected
# ---------------------------------------------------------------------------

def test_ask_with_valid_role_injects_personality():
    """With a valid role, _build_system_prompt should include the role's
    personality in the system prompt passed to generate_answer.
    """
    # Use a role that exists in DEFAULT_ROLES
    valid_role = DEFAULT_ROLES[0]["role"]  # "manager"
    personality = DEFAULT_ROLES[0]["personality"]

    chunks = [{"document_name": "doc1", "text": "chunk"}]

    mock_gen = _mock_generation({
        "answer": "answer", "sources": [], "provider_used": "gemini",
        "usage": None, "chunks_sent": 1, "fallback_used": False,
    })

    with patch.object(chat, "_prepare", return_value=(chunks, "en", False)), \
         patch.object(chat, "GenerationService", mock_gen), \
         patch.object(chat, "record_trace"), \
         patch.object(employee_skills, "get_role_personality", return_value=personality), \
         patch.object(employee_skills, "get_role_skills_with_ids", return_value=("role context", ["mem-1"])), \
         patch.object(employee_memory, "get_owner_instructions", return_value=""):
        chat.ask("question", role=valid_role)

    gen_instance = mock_gen.return_value
    call_kwargs = gen_instance.generate_answer.call_args
    sys_prompt = call_kwargs.kwargs.get("system_prompt") or \
                 (call_kwargs.args[2] if len(call_kwargs.args) > 2 else None)

    assert sys_prompt is not None
    assert personality in sys_prompt
    assert "role context" in sys_prompt


def test_ask_with_valid_role_returns_memory_ids():
    """ask() should return role_memory_ids from _build_system_prompt."""
    valid_role = DEFAULT_ROLES[0]["role"]

    mock_gen = _mock_generation({
        "answer": "answer", "sources": [], "provider_used": "gemini",
        "usage": None, "chunks_sent": 1, "fallback_used": False,
    })

    with patch.object(chat, "_prepare", return_value=([], "en", False)), \
         patch.object(chat, "GenerationService", mock_gen), \
         patch.object(chat, "record_trace"), \
         patch.object(employee_skills, "get_role_personality", return_value="personality"), \
         patch.object(employee_skills, "get_role_skills_with_ids", return_value=("ctx", ["mem-42", "mem-99"])), \
         patch.object(employee_memory, "get_owner_instructions", return_value=""):
        result = chat.ask("question", role=valid_role)

    assert result["role_memory_ids"] == ["mem-42", "mem-99"]


# ---------------------------------------------------------------------------
# 3. ask() with nonexistent role — graceful fallback
# ---------------------------------------------------------------------------

def test_ask_with_nonexistent_role_no_error():
    """A role not in DEFAULT_ROLES or DB should not raise — falls back to
    defaults.DEFAULT_ROLES personality (empty string if not found).
    """
    fake_role = "nonexistent_role_xyz"

    mock_gen = _mock_generation({
        "answer": "answer", "sources": [], "provider_used": "gemini",
        "usage": None, "chunks_sent": 1, "fallback_used": False,
    })

    with patch.object(chat, "_prepare", return_value=([], "en", False)), \
         patch.object(chat, "GenerationService", mock_gen), \
         patch.object(chat, "record_trace"), \
         patch.object(employee_skills, "get_role_personality", return_value=""), \
         patch.object(employee_skills, "get_role_skills_with_ids", return_value=("", [])), \
         patch.object(employee_memory, "get_owner_instructions", return_value=""):
        # Should not raise
        result = chat.ask("question", role=fake_role)

    assert result["answer"] == "answer"


# ---------------------------------------------------------------------------
# 4. Owner instructions appear in augmented query
# ---------------------------------------------------------------------------

def test_augment_query_with_reminder_appends_owner_instructions():
    """_augment_query_with_reminder should append owner instructions to the
    query when both role and owner_instructions are present.
    """
    owner_text = "=== OWNER INSTRUCTIONS (obey always) ===\nAlways say hello first."
    with patch.object(employee_memory, "get_owner_instructions", return_value=owner_text):
        result = chat._augment_query_with_reminder("support", "what is X?")

    assert "what is X?" in result
    assert "Always say hello first." in result
    assert "Reminder" in result or "reminder" in result.lower()


def test_augment_query_without_role_returns_query_unchanged():
    """Without role, _augment_query_with_reminder returns query as-is."""
    result = chat._augment_query_with_reminder(None, "what is X?")
    assert result == "what is X?"


def test_augment_query_with_role_but_no_owner_instructions():
    """With role but no owner instructions, query is returned unchanged."""
    with patch.object(employee_memory, "get_owner_instructions", return_value=""):
        result = chat._augment_query_with_reminder("support", "what is X?")
    assert result == "what is X?"


def test_ask_with_role_and_owner_instructions_in_augmented_query():
    """End-to-end: owner instructions set via PATCH /profile should appear
    in the augmented query passed to generate_answer.
    """
    owner_text = "=== OWNER INSTRUCTIONS (obey always) ===\nAlways say hello first."
    valid_role = DEFAULT_ROLES[0]["role"]

    mock_gen = _mock_generation({
        "answer": "answer", "sources": [], "provider_used": "gemini",
        "usage": None, "chunks_sent": 1, "fallback_used": False,
    })

    with patch.object(chat, "_prepare", return_value=([], "en", False)), \
         patch.object(chat, "GenerationService", mock_gen), \
         patch.object(chat, "record_trace"), \
         patch.object(employee_skills, "get_role_personality", return_value="personality"), \
         patch.object(employee_skills, "get_role_skills_with_ids", return_value=("ctx", [])), \
         patch.object(employee_memory, "get_owner_instructions", return_value=owner_text):
        chat.ask("what is X?", role=valid_role)

    gen_instance = mock_gen.return_value
    call_args = gen_instance.generate_answer.call_args
    # First positional arg is the augmented query
    augmented_query = call_args.args[0] if call_args.args else call_args.kwargs.get("query")
    assert augmented_query is not None
    assert "Always say hello first." in augmented_query
    assert "what is X?" in augmented_query


# ---------------------------------------------------------------------------
# 5. _build_system_prompt unit tests
# ---------------------------------------------------------------------------

def test_build_system_prompt_no_role_returns_base():
    result, ids = chat._build_system_prompt(None, "query", "base prompt")
    assert result == "base prompt"
    assert ids == []


def test_build_system_prompt_no_role_no_base_returns_none():
    result, ids = chat._build_system_prompt(None, "query", None)
    assert result is None
    assert ids == []


def test_build_system_prompt_with_role_and_personality():
    personality = "You are a helpful manager."
    role_context = "Some business context"
    with patch.object(employee_skills, "get_role_personality", return_value=personality), \
         patch.object(employee_skills, "get_role_skills_with_ids", return_value=(role_context, ["m1"])):
        result, ids = chat._build_system_prompt("manager", "query", "base")

    assert result is not None
    assert personality in result
    assert role_context in result
    assert ids == ["m1"]


def test_build_system_prompt_with_owner_instructions_in_context():
    """When role_context contains OWNER INSTRUCTIONS, they should be
    extracted into a MANDATORY block at the top.
    """
    owner_block = "=== OWNER INSTRUCTIONS (obey always) ===\nAlways say hello first."
    role_context = owner_block + "\n\nSome other context"
    with patch.object(employee_skills, "get_role_personality", return_value=""), \
         patch.object(employee_skills, "get_role_skills_with_ids", return_value=(role_context, [])):
        result, ids = chat._build_system_prompt("manager", "query", "base")

    assert result is not None
    assert "MANDATORY" in result
    assert "Always say hello first." in result
    # The owner block should be at the start
    assert result.index("MANDATORY") < result.index("Some other context")


# ---------------------------------------------------------------------------
# 6. is_sensitive_role integration
# ---------------------------------------------------------------------------

def test_sensitive_role_triggers_reflection():
    """Sensitive roles should trigger check_grounding (reflection)."""
    from core.employees.defaults import SENSITIVE_DOMAIN_ROLES

    if not SENSITIVE_DOMAIN_ROLES:
        # Skip if no sensitive roles defined
        return

    sensitive_role = next(iter(SENSITIVE_DOMAIN_ROLES))

    mock_gen = _mock_generation({
        "answer": "answer", "sources": [], "provider_used": "gemini",
        "usage": None, "chunks_sent": 1, "fallback_used": False,
    })
    mock_gen.return_value.check_grounding.return_value = None

    with patch.object(chat, "_prepare", return_value=([], "en", False)), \
         patch.object(chat, "GenerationService", mock_gen), \
         patch.object(chat, "record_trace"), \
         patch.object(employee_skills, "get_role_personality", return_value=""), \
         patch.object(employee_skills, "get_role_skills_with_ids", return_value=("", [])), \
         patch.object(employee_memory, "get_owner_instructions", return_value=""):
        chat.ask("question", role=sensitive_role)

    mock_gen.return_value.check_grounding.assert_called_once()
