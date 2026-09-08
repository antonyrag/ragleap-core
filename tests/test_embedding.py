"""
Tests for core/embedding.py - same-provider retry-on-transient-error logic.
No live API calls - google.genai.Client is mocked directly. Deliberately
does NOT test cross-provider fallback because there isn't one: every stored
chunk is embedded via this exact model/dimensions, so a different provider
would land in a different, incompatible vector space (see embedding.py's
module docstring/comments for why).
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test-key-for-mocked-tests")

from core import embedding
from core.embedding import EmbeddingService


# Other test files in this suite (test_bigquery_connector.py,
# test_gmail_connector.py) replace sys.modules['google'] with a
# MagicMock at import time to stub a heavy optional dependency, with no
# cleanup - this leaks into any test running later in the same pytest
# process and breaks a real `import google.genai`, which is what
# core/embedding.py needs. Capture the REAL google.genai modules once,
# here at collection time (forcing one real import if needed), so the
# per-test fixture below only has to do cheap dict swaps rather than a
# fresh heavy SDK import on every single test.
_saved_at_collection = {k: v for k, v in sys.modules.items() if k == "google" or k.startswith("google.")}
for _k in list(_saved_at_collection):
    del sys.modules[_k]
import google.genai  # noqa: F401 - forces one real import, now cached below
_REAL_GOOGLE_MODULES = {k: v for k, v in sys.modules.items() if k == "google" or k.startswith("google.")}
for _k in list(sys.modules):
    if _k == "google" or _k.startswith("google."):
        del sys.modules[_k]
sys.modules.update(_saved_at_collection)  # restore whatever state collection order left us with


@pytest.fixture(autouse=True)
def _real_google_genai_import():
    """Swap in the real, pre-imported google.genai modules (cheap dict
    update, no re-import) before each test, and restore prior state
    after - see the module-level comment above for why this is needed."""
    saved = {k: v for k, v in sys.modules.items() if k == "google" or k.startswith("google.")}
    for k in list(saved):
        del sys.modules[k]
    sys.modules.update(_REAL_GOOGLE_MODULES)
    yield
    for k in list(sys.modules):
        if k == "google" or k.startswith("google."):
            del sys.modules[k]
    sys.modules.update(saved)


class FakeAPIError(Exception):
    """Mimics google.genai.errors.APIError's shape: a .code attribute."""
    def __init__(self, code, message="fake api error"):
        self.code = code
        super().__init__(f"{code} {message}")


def _make_response(values):
    resp = MagicMock()
    resp.embeddings = [MagicMock(values=values)]
    return resp


def test_embed_text_succeeds_first_try_no_retry():
    service = EmbeddingService()
    mock_client = MagicMock()
    mock_client.models.embed_content.return_value = _make_response([0.1, 0.2])
    with patch("google.genai.Client", return_value=mock_client):
        result = service.embed_text("hello")
    assert result == [0.1, 0.2]
    assert mock_client.models.embed_content.call_count == 1


def test_embed_text_retries_on_429_then_succeeds():
    service = EmbeddingService()
    mock_client = MagicMock()
    mock_client.models.embed_content.side_effect = [
        FakeAPIError(429),
        FakeAPIError(429),
        _make_response([0.3, 0.4]),
    ]
    with patch("google.genai.Client", return_value=mock_client), \
         patch("time.sleep"):  # skip real backoff delay in tests
        result = service.embed_text("hello")
    assert result == [0.3, 0.4]
    assert mock_client.models.embed_content.call_count == 3


def test_embed_text_retries_on_503_then_succeeds():
    service = EmbeddingService()
    mock_client = MagicMock()
    mock_client.models.embed_content.side_effect = [
        FakeAPIError(503),
        _make_response([0.5]),
    ]
    with patch("google.genai.Client", return_value=mock_client), \
         patch("time.sleep"):
        result = service.embed_text("hello")
    assert result == [0.5]
    assert mock_client.models.embed_content.call_count == 2


def test_embed_text_does_not_retry_on_non_transient_error():
    """A 401/403 (bad key) or 400 (malformed request) should fail fast,
    not burn retries - retrying a permanently-broken key just wastes time."""
    service = EmbeddingService()
    mock_client = MagicMock()
    mock_client.models.embed_content.side_effect = FakeAPIError(401, "invalid api key")
    with patch("google.genai.Client", return_value=mock_client), \
         patch("time.sleep") as mock_sleep:
        result = service.embed_text("hello")
    assert result is None
    assert mock_client.models.embed_content.call_count == 1
    mock_sleep.assert_not_called()


def test_embed_text_gives_up_after_max_retries():
    service = EmbeddingService()
    mock_client = MagicMock()
    mock_client.models.embed_content.side_effect = FakeAPIError(429)  # always fails
    with patch("google.genai.Client", return_value=mock_client), \
         patch("time.sleep"):
        result = service.embed_text("hello")
    assert result is None
    # initial attempt + EMBEDDING_MAX_RETRIES retries
    assert mock_client.models.embed_content.call_count == embedding.EMBEDDING_MAX_RETRIES + 1


def test_embed_batch_retries_on_transient_error():
    service = EmbeddingService()
    mock_client = MagicMock()
    mock_client.models.embed_content.side_effect = [
        FakeAPIError(429),
        _make_response(None).__class__() if False else MagicMock(
            embeddings=[MagicMock(values=[0.1]), MagicMock(values=[0.2])]
        ),
    ]
    with patch("google.genai.Client", return_value=mock_client), \
         patch("time.sleep"):
        result = service.embed_batch(["a", "b"])
    assert result == [[0.1], [0.2]]
    assert mock_client.models.embed_content.call_count == 2


def test_embed_batch_empty_input_returns_empty_no_api_call():
    service = EmbeddingService()
    mock_client = MagicMock()
    with patch("google.genai.Client", return_value=mock_client):
        result = service.embed_batch([])
    assert result == []
    mock_client.models.embed_content.assert_not_called()


def test_embed_text_empty_string_returns_none_no_api_call():
    service = EmbeddingService()
    mock_client = MagicMock()
    with patch("google.genai.Client", return_value=mock_client):
        result = service.embed_text("   ")
    assert result is None
    mock_client.models.embed_content.assert_not_called()
