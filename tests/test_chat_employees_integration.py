"""
Tests for /chat role wiring (issue #134): _build_system_prompt,
_augment_query_with_reminder, the ask() integration of both, and the
/chat + /chat/stream HTTP routes themselves (see the route section at the
bottom of this file).

No real DB, embedding, or LLM calls — all collaborators are patched.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

# core/api.py's module-level setup reads DATABASE_URL at import time (it does
# not connect); importing it here is what lets the route tests below drive the
# real app instead of calling the endpoint functions by hand.
os.environ.setdefault("DATABASE_URL", "postgresql://ragleap:ragleap@localhost:5433/ragleap_core")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import api as core_api
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


# ---------------------------------------------------------------------------
# 7. Route-level tests: the HTTP surface of /chat and /chat/stream
#
# The tests above drive chat.ask() directly. These drive the real FastAPI app
# through a TestClient instead, so what is pinned is the route: the query
# parameters it accepts, the role it forwards, the JSON body it returns, and
# what a caller sees when the model call fails.
#
# TestClient is not used as a context manager, so the app's lifespan never
# runs: no scheduler is started and no database connection is opened.
# ---------------------------------------------------------------------------

_ASK_RESULT = {
    "answer": "The office is open 9-5.",
    "sources": ["handbook.pdf"],
    "chunks_used": 2,
    "chunks_sent": 2,
    "detected_language": "en",
    "provider_used": "gemini",
    "usage": {"prompt_tokens": 120, "completion_tokens": 12, "total_tokens": 132},
    "role_memory_ids": ["mem-1"],
}


@pytest.fixture
def client(monkeypatch):
    """TestClient over the real app, with API-key auth switched off.

    RAGLEAP_API_KEY is read from the module global on every request, so a
    deployment that has it set in .env does not turn these tests into 401s.
    """
    monkeypatch.setattr(core_api, "RAGLEAP_API_KEY", "")
    return TestClient(core_api.app)


def test_chat_route_forwards_role_to_ask(client, monkeypatch):
    calls = {}

    def fake_ask(question, **kwargs):
        calls["question"] = question
        calls["kwargs"] = kwargs
        return dict(_ASK_RESULT)

    monkeypatch.setattr(core_api, "ask", fake_ask)

    response = client.post(
        "/chat",
        params={"question": "What are your hours?", "role": "hr_manager", "top_k": 3},
    )

    assert response.status_code == 200
    assert calls["question"] == "What are your hours?"
    assert calls["kwargs"]["role"] == "hr_manager"
    assert calls["kwargs"]["top_k"] == 3
    body = response.json()
    assert body["answer"] == "The office is open 9-5."
    assert body["sources"] == ["handbook.pdf"]
    assert body["role_memory_ids"] == ["mem-1"]


def test_chat_route_without_role_forwards_none(client, monkeypatch):
    """Pre-#133 behaviour: no role parameter means no role context."""
    calls = {}

    def fake_ask(question, **kwargs):
        calls["kwargs"] = kwargs
        return dict(_ASK_RESULT)

    monkeypatch.setattr(core_api, "ask", fake_ask)

    response = client.post("/chat", params={"question": "What are your hours?"})

    assert response.status_code == 200
    assert calls["kwargs"]["role"] is None


def test_chat_route_rejects_a_blank_question_before_the_model_is_called(client, monkeypatch):
    def fake_ask(*args, **kwargs):
        raise AssertionError("ask() must not be reached for an invalid question")

    monkeypatch.setattr(core_api, "ask", fake_ask)

    response = client.post("/chat", params={"question": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Question cannot be empty."


def test_chat_route_rejects_a_question_over_the_length_limit(client, monkeypatch):
    monkeypatch.setattr(core_api, "ask", lambda *args, **kwargs: pytest.fail("ask() must not be reached"))

    response = client.post("/chat", params={"question": "x" * (core_api.MAX_QUESTION_LENGTH + 1)})

    assert response.status_code == 400
    assert "too long" in response.json()["detail"]


def test_chat_route_reports_a_failed_model_call_as_500_without_leaking_it(client, monkeypatch):
    def fake_ask(*args, **kwargs):
        raise RuntimeError("provider rejected key sk-live-abc123")

    monkeypatch.setattr(core_api, "ask", fake_ask)

    response = client.post("/chat", params={"question": "What are your hours?", "role": "hr_manager"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Chat failed. See server logs for details."
    assert "sk-live-abc123" not in response.text


def test_chat_stream_route_forwards_role_and_streams_the_text(client, monkeypatch):
    calls = {}

    def fake_ask_stream(question, **kwargs):
        calls["question"] = question
        calls["kwargs"] = kwargs
        yield "The office "
        yield "is open 9-5."

    monkeypatch.setattr(core_api, "ask_stream", fake_ask_stream)

    response = client.post(
        "/chat/stream",
        params={"question": "What are your hours?", "role": "hr_manager"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "The office is open 9-5."
    assert calls["question"] == "What are your hours?"
    assert calls["kwargs"]["role"] == "hr_manager"


def test_chat_stream_route_without_role_forwards_none(client, monkeypatch):
    calls = {}

    def fake_ask_stream(question, **kwargs):
        calls["kwargs"] = kwargs
        yield "ok"

    monkeypatch.setattr(core_api, "ask_stream", fake_ask_stream)

    response = client.post("/chat/stream", params={"question": "hi"})

    assert response.status_code == 200
    assert calls["kwargs"]["role"] is None


def test_chat_stream_route_ends_with_an_error_line_instead_of_crashing(client, monkeypatch):
    """A failure mid-stream cannot become a 500 — the status line is already on
    the wire — so the route ends the body with its error line."""
    def fake_ask_stream(question, **kwargs):
        yield "partial answer"
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(core_api, "ask_stream", fake_ask_stream)

    response = client.post("/chat/stream", params={"question": "What are your hours?"})

    assert response.status_code == 200
    assert response.text == "partial answer\n[Error: the request could not be completed]"


def test_chat_stream_route_rejects_a_blank_question_before_streaming(client, monkeypatch):
    monkeypatch.setattr(core_api, "ask_stream", lambda *args, **kwargs: pytest.fail("ask_stream() must not be reached"))

    response = client.post("/chat/stream", params={"question": ""})

    assert response.status_code == 400
    assert response.json()["detail"] == "Question cannot be empty."
