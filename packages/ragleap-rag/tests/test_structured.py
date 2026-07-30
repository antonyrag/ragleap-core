"""Tests for structured/JSON output mode (v0.8.0). Split into two
groups: unit tests for ragleap.structured's parse/validate logic
(including a forced no-jsonschema fallback path via monkeypatching,
since jsonschema IS installed in this test environment), and plumbing
tests proving response_format= flows correctly through ask() ->
generate_answer() -> the provider call and back, using the existing
fake_call_provider fixture (no live network calls - live Gemini/
Anthropic verification was done manually this session, documented in
CHANGELOG, since it needs a real committed API key CI doesn't have)."""
import pytest
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap.structured import parse_and_validate, parse_and_validate_object
from conftest import TEST_DATABASE_URL, TEST_DIMENSIONS


def _make_rag(**kwargs):
    return RagLeap(
        database_url=TEST_DATABASE_URL,
        embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
        **kwargs,
    )


SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}


# --- ragleap.structured unit tests ---

def test_parse_and_validate_valid_json_matching_schema():
    parsed, is_valid, method = parse_and_validate('{"name": "test"}', SCHEMA)
    assert parsed == {"name": "test"}
    assert is_valid is True
    assert method == "jsonschema"


def test_parse_and_validate_valid_json_not_matching_schema():
    """Missing the required 'name' field - valid JSON, invalid per schema."""
    parsed, is_valid, method = parse_and_validate('{"other": "value"}', SCHEMA)
    assert parsed == {"other": "value"}
    assert is_valid is False
    assert method == "jsonschema"


def test_parse_and_validate_malformed_json_returns_none():
    parsed, is_valid, method = parse_and_validate("not valid json{{{", SCHEMA)
    assert parsed is None
    assert is_valid is False


def test_parse_and_validate_object_valid():
    """Mirrors Anthropic's tool-use path, which hands back an already-
    parsed dict rather than a JSON string."""
    parsed, is_valid, method = parse_and_validate_object({"name": "test"}, SCHEMA)
    assert parsed == {"name": "test"}
    assert is_valid is True
    assert method == "jsonschema"


def test_parse_and_validate_without_jsonschema_installed(monkeypatch):
    """Forces the basic-type-check-only fallback path by monkeypatching
    HAS_JSONSCHEMA, since jsonschema IS actually installed in this
    test environment - proves the honest-degradation path really works,
    not just that it exists in the source."""
    import ragleap.structured as structured_module
    monkeypatch.setattr(structured_module, "HAS_JSONSCHEMA", False)

    # Missing required 'name' - basic type check only verifies it's a
    # dict (matches type: object), doesn't know about `required`, so
    # this incorrectly reports valid=True. That's the documented
    # limitation, not a bug - the test locks in the honest behavior.
    parsed, is_valid, method = structured_module.parse_and_validate('{"other": "value"}', SCHEMA)
    assert parsed == {"other": "value"}
    assert is_valid is True  # basic check can't catch missing required fields
    assert method == "basic_type_check_only"

    # But it DOES catch a top-level type mismatch
    parsed2, is_valid2, method2 = structured_module.parse_and_validate('["not", "an", "object"]', SCHEMA)
    assert is_valid2 is False
    assert method2 == "basic_type_check_only"


def test_parse_and_validate_invalid_schema_itself():
    """A malformed schema (invalid 'type' value) should be caught as a
    SchemaError, not crash the caller."""
    bad_schema = {"type": "not-a-real-json-schema-type"}
    parsed, is_valid, method = parse_and_validate('{"x": 1}', bad_schema)
    assert is_valid is False


# --- Plumbing tests: response_format= flows through ask() correctly ---

def test_ask_without_response_format_has_no_structured_fields():
    """Backward compatibility - existing callers who never pass
    response_format shouldn't see new keys cluttering the result."""
    rag = _make_rag()
    rag.ingest_text("a.txt", "Some content about testing things.")

    result = rag.ask("A question")

    assert "structured" not in result
    assert "structured_valid" not in result
    assert "structured_enforcement" not in result


def test_ask_with_response_format_returns_structured_fields():
    """Uses a permissive schema matching fake_call_provider's canned
    {"result": "fake"} payload shape, so this specifically tests the
    plumbing (result keys present, JSON parsed correctly) rather than
    validation strictness - see the next test for that."""
    permissive_schema = {"type": "object", "properties": {"result": {"type": "string"}}}
    rag = _make_rag()
    rag.ingest_text("a.txt", "Some content about testing things.")

    result = rag.ask("A question", response_format=permissive_schema)

    assert "structured" in result
    assert result["structured"] == {"result": "fake"}
    assert result["structured_valid"] is True
    assert result["structured_enforcement"] == "native"
    assert result["structured_validation_method"] == "jsonschema"
    # "answer" still contains the JSON as a string, for backward compat
    assert result["answer"] == '{"result": "fake"}'


def test_ask_with_response_format_catches_real_schema_mismatch():
    """SCHEMA requires a "name" field that the fake fixture's canned
    payload doesn't have - proves real jsonschema validation runs
    through the full ask() call, not a rubber-stamped True."""
    rag = _make_rag()
    rag.ingest_text("a.txt", "Some content about testing things.")

    result = rag.ask("A question", response_format=SCHEMA)

    assert result["structured"] == {"result": "fake"}
    assert result["structured_valid"] is False
    assert result["structured_validation_method"] == "jsonschema"


def test_ask_with_response_format_array_schema():
    """Confirms the fake fixture (and real plumbing) respects the
    schema's declared top-level type, not just always returning an
    object."""
    rag = _make_rag()
    rag.ingest_text("a.txt", "Some content.")

    array_schema = {"type": "array", "items": {"type": "string"}}
    result = rag.ask("A question", response_format=array_schema)

    assert result["structured"] == ["fake"]
    assert result["structured_valid"] is True


def test_ask_with_response_format_and_guardrails_still_work():
    """response_format's JSON-string answer still passes through the
    existing output_guardrails machinery without special-casing."""
    def uppercase_guardrail(text):
        return text.upper()

    rag = _make_rag(output_guardrails=[uppercase_guardrail])
    rag.ingest_text("a.txt", "Some content.")

    result = rag.ask("A question", response_format=SCHEMA)

    assert result["answer"] == '{"RESULT": "FAKE"}'
    assert result["guardrail_blocked"] is False
