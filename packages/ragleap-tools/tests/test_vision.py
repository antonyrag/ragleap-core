"""Tests for ragleap_tools.vision - image-type detection, the
describe_image() validation order, the two reference providers, and
make_vision_tool(). A FakeVisionProvider records every call so tests
assert on what was actually passed through (and that rejected inputs
never reach the provider); urllib.request.urlopen is mocked directly
for the provider tests so each provider's real URL/header/body
construction is exercised, not bypassed."""
import base64
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from ragleap_tools.file_ops import FileOpsConfig
from ragleap_tools.vision import (
    DEFAULT_PROMPT,
    AnthropicVisionProvider,
    GeminiVisionProvider,
    VisionConfig,
    VisionProvider,
    _detect_mime_type,
    describe_image,
    make_vision_tool,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32


class FakeVisionProvider(VisionProvider):
    supported_mime_types = frozenset({"image/jpeg", "image/png", "image/webp"})

    def __init__(self, description="a cat", raise_error=None, supported=None):
        self._description = description
        self._raise_error = raise_error
        self.calls = []
        if supported is not None:
            self.supported_mime_types = frozenset(supported)

    def describe(self, image_bytes, mime_type, prompt):
        self.calls.append({"image_bytes": image_bytes, "mime_type": mime_type, "prompt": prompt})
        if self._raise_error is not None:
            raise self._raise_error
        return self._description


def _make(tmp_path, provider=None, **kwargs):
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    provider = provider or FakeVisionProvider()
    config = VisionConfig(provider=provider, sandbox=FileOpsConfig(root_dir=str(root)), **kwargs)
    return config, provider, root


def _fake_response(payload: dict):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(payload).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    return mock_response


def _headers(request):
    return {k.lower(): v for k, v in request.header_items()}


# --- _detect_mime_type ---

def test_detect_mime_type_known_formats():
    assert _detect_mime_type(PNG) == "image/png"
    assert _detect_mime_type(JPEG) == "image/jpeg"
    assert _detect_mime_type(GIF) == "image/gif"
    assert _detect_mime_type(WEBP) == "image/webp"
    assert _detect_mime_type(b"GIF87a" + b"\x00" * 8) == "image/gif"


def test_detect_mime_type_unknown_and_short():
    assert _detect_mime_type(b"hello world, not an image") is None
    assert _detect_mime_type(b"") is None
    assert _detect_mime_type(b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 8) is None


# --- describe_image: success and pass-through ---

def test_describe_image_success_passes_bytes_type_and_default_prompt(tmp_path):
    config, provider, root = _make(tmp_path)
    (root / "a.png").write_bytes(PNG)
    result = describe_image(config, "a.png")
    assert result.success is True
    assert result.result == {"description": "a cat"}
    assert provider.calls == [{"image_bytes": PNG, "mime_type": "image/png", "prompt": DEFAULT_PROMPT}]


def test_describe_image_passes_custom_prompt_through(tmp_path):
    config, provider, root = _make(tmp_path)
    (root / "a.png").write_bytes(PNG)
    describe_image(config, "a.png", prompt="How many cats?")
    assert provider.calls[0]["prompt"] == "How many cats?"


def test_blank_prompt_falls_back_to_default(tmp_path):
    config, provider, root = _make(tmp_path)
    (root / "a.png").write_bytes(PNG)
    describe_image(config, "a.png", prompt="   ")
    assert provider.calls[0]["prompt"] == DEFAULT_PROMPT


def test_type_is_detected_from_bytes_not_extension(tmp_path):
    config, provider, root = _make(tmp_path)
    (root / "actually_png.jpg").write_bytes(PNG)
    result = describe_image(config, "actually_png.jpg")
    assert result.success is True
    assert provider.calls[0]["mime_type"] == "image/png"


def test_description_is_stripped(tmp_path):
    config, _, root = _make(tmp_path, provider=FakeVisionProvider(description="  hello \n"))
    (root / "a.png").write_bytes(PNG)
    assert describe_image(config, "a.png").result == {"description": "hello"}


# --- describe_image: validation (provider must never be called) ---

def test_prompt_too_long_rejected(tmp_path):
    config, provider, root = _make(tmp_path, max_prompt_chars=10)
    (root / "a.png").write_bytes(PNG)
    result = describe_image(config, "a.png", prompt="x" * 11)
    assert result.success is False
    assert "too long" in result.error
    assert provider.calls == []


def test_non_string_prompt_rejected(tmp_path):
    config, provider, root = _make(tmp_path)
    (root / "a.png").write_bytes(PNG)
    result = describe_image(config, "a.png", prompt=123)
    assert result.success is False
    assert "prompt must be a string" in result.error
    assert provider.calls == []


def test_path_traversal_rejected(tmp_path):
    config, provider, _ = _make(tmp_path)
    (tmp_path / "outside.png").write_bytes(PNG)
    result = describe_image(config, "../outside.png")
    assert result.success is False
    assert "PathEscapeError" in result.error
    assert provider.calls == []


def test_absolute_path_rejected(tmp_path):
    config, provider, _ = _make(tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    result = describe_image(config, str(outside))
    assert result.success is False
    assert "PathEscapeError" in result.error
    assert provider.calls == []


def test_symlink_escape_rejected(tmp_path):
    config, provider, root = _make(tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    (root / "link.png").symlink_to(outside)
    result = describe_image(config, "link.png")
    assert result.success is False
    assert "PathEscapeError" in result.error
    assert provider.calls == []


def test_missing_file_and_directory_rejected(tmp_path):
    config, provider, root = _make(tmp_path)
    (root / "subdir").mkdir()
    assert describe_image(config, "nope.png").success is False
    result = describe_image(config, "subdir")
    assert result.success is False
    assert "Not a file" in result.error
    assert provider.calls == []


def test_missing_or_non_string_path_rejected(tmp_path):
    config, provider, _ = _make(tmp_path)
    assert describe_image(config, "").success is False
    assert describe_image(config, None).success is False
    assert provider.calls == []


def test_nonexistent_sandbox_root_returns_error(tmp_path):
    provider = FakeVisionProvider()
    config = VisionConfig(provider=provider, sandbox=FileOpsConfig(root_dir=str(tmp_path / "missing")))
    result = describe_image(config, "a.png")
    assert result.success is False
    assert provider.calls == []


def test_oversize_image_rejected_before_provider(tmp_path):
    config, provider, root = _make(tmp_path, max_image_bytes=40)
    (root / "big.png").write_bytes(PNG)  # 40 bytes exactly is allowed...
    assert describe_image(config, "big.png").success is True
    (root / "bigger.png").write_bytes(PNG + b"\x00")  # ...41 is not
    result = describe_image(config, "bigger.png")
    assert result.success is False
    assert "too large" in result.error
    assert len(provider.calls) == 1


def test_empty_file_rejected(tmp_path):
    config, provider, root = _make(tmp_path)
    (root / "empty.png").write_bytes(b"")
    result = describe_image(config, "empty.png")
    assert result.success is False
    assert "empty" in result.error
    assert provider.calls == []


def test_non_image_with_image_extension_rejected(tmp_path):
    config, provider, root = _make(tmp_path)
    (root / "fake.png").write_text("this is not an image")
    result = describe_image(config, "fake.png")
    assert result.success is False
    assert "Unrecognized image format" in result.error
    assert provider.calls == []


def test_type_not_supported_by_provider_rejected(tmp_path):
    config, provider, root = _make(tmp_path, provider=FakeVisionProvider(supported={"image/png"}))
    (root / "a.gif").write_bytes(GIF)
    result = describe_image(config, "a.gif")
    assert result.success is False
    assert "image/gif" in result.error
    assert provider.calls == []


# --- describe_image: provider failures become ToolResults, never raise ---

def test_http_error_becomes_tool_result(tmp_path):
    err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)
    config, _, root = _make(tmp_path, provider=FakeVisionProvider(raise_error=err))
    (root / "a.png").write_bytes(PNG)
    result = describe_image(config, "a.png")
    assert result.success is False
    assert "401" in result.error and "Unauthorized" in result.error


def test_url_error_becomes_tool_result(tmp_path):
    config, _, root = _make(tmp_path, provider=FakeVisionProvider(raise_error=urllib.error.URLError("boom")))
    (root / "a.png").write_bytes(PNG)
    result = describe_image(config, "a.png")
    assert result.success is False
    assert "Network error" in result.error


def test_response_shape_error_becomes_tool_result(tmp_path):
    config, _, root = _make(tmp_path, provider=FakeVisionProvider(raise_error=KeyError("candidates")))
    (root / "a.png").write_bytes(PNG)
    result = describe_image(config, "a.png")
    assert result.success is False
    assert "Unexpected response shape" in result.error


def test_unexpected_provider_exception_becomes_tool_result(tmp_path):
    config, _, root = _make(tmp_path, provider=FakeVisionProvider(raise_error=RuntimeError("weird")))
    (root / "a.png").write_bytes(PNG)
    result = describe_image(config, "a.png")
    assert result.success is False
    assert "RuntimeError" in result.error


def test_empty_description_becomes_tool_result(tmp_path):
    config, _, root = _make(tmp_path, provider=FakeVisionProvider(description="   "))
    (root / "a.png").write_bytes(PNG)
    result = describe_image(config, "a.png")
    assert result.success is False
    assert "no description" in result.error


# --- GeminiVisionProvider ---

def test_gemini_builds_real_request_and_parses_text():
    payload = {"candidates": [{"content": {"parts": [{"text": "A red "}, {"text": "square."}]}}]}
    provider = GeminiVisionProvider(api_key="secret-key", model="gemini-test")
    with patch("ragleap_tools.vision.urllib.request.urlopen", return_value=_fake_response(payload)) as m:
        out = provider.describe(PNG, "image/png", "What is it?")
    assert out == "A red square."
    request = m.call_args[0][0]
    assert request.full_url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    assert "secret-key" not in request.full_url
    assert request.get_method() == "POST"
    headers = _headers(request)
    assert headers["x-goog-api-key"] == "secret-key"
    assert headers["content-type"] == "application/json"
    parts = json.loads(request.data)["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/png"
    assert base64.b64decode(parts[0]["inline_data"]["data"]) == PNG
    assert parts[1] == {"text": "What is it?"}
    assert m.call_args[1]["timeout"] == 60


def test_gemini_no_text_raises_value_error():
    provider = GeminiVisionProvider(api_key="k", model="m")
    payload = {"candidates": [{"content": {"parts": []}}]}
    with patch("ragleap_tools.vision.urllib.request.urlopen", return_value=_fake_response(payload)):
        with pytest.raises(ValueError):
            provider.describe(PNG, "image/png", "p")


def test_gemini_requires_api_key_and_model():
    with pytest.raises(ValueError):
        GeminiVisionProvider(api_key="", model="m")
    with pytest.raises(ValueError):
        GeminiVisionProvider(api_key="k", model="  ")


# --- AnthropicVisionProvider ---

def test_anthropic_builds_real_request_and_parses_text():
    payload = {"content": [{"type": "text", "text": "A "}, {"type": "other"}, {"type": "text", "text": "cat"}]}
    provider = AnthropicVisionProvider(api_key="secret-key", model="claude-test", max_tokens=256)
    with patch("ragleap_tools.vision.urllib.request.urlopen", return_value=_fake_response(payload)) as m:
        out = provider.describe(JPEG, "image/jpeg", "Describe.")
    assert out == "A cat"
    request = m.call_args[0][0]
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    assert request.get_method() == "POST"
    headers = _headers(request)
    assert headers["x-api-key"] == "secret-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["content-type"] == "application/json"
    body = json.loads(request.data)
    assert body["model"] == "claude-test"
    assert body["max_tokens"] == 256
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["type"] == "base64"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(content[0]["source"]["data"]) == JPEG
    assert content[1] == {"type": "text", "text": "Describe."}


def test_anthropic_no_text_raises_value_error():
    provider = AnthropicVisionProvider(api_key="k", model="m")
    with patch("ragleap_tools.vision.urllib.request.urlopen", return_value=_fake_response({"content": []})):
        with pytest.raises(ValueError):
            provider.describe(PNG, "image/png", "p")


def test_anthropic_requires_api_key_and_model():
    with pytest.raises(ValueError):
        AnthropicVisionProvider(api_key="", model="m")
    with pytest.raises(ValueError):
        AnthropicVisionProvider(api_key="k", model="")


def test_reference_providers_declare_supported_types():
    assert "image/gif" in AnthropicVisionProvider.supported_mime_types
    assert "image/gif" not in GeminiVisionProvider.supported_mime_types


# --- make_vision_tool ---

def test_make_vision_tool_schema_and_call(tmp_path):
    config, provider, root = _make(tmp_path)
    (root / "a.png").write_bytes(PNG)
    tool = make_vision_tool(config)
    assert tool.name == "describe_image"
    assert tool.parameters["required"] == ["path"]
    assert set(tool.parameters["properties"]) == {"path", "prompt"}
    result = tool.call(path="a.png", prompt="Q?")
    assert result.success is True
    assert provider.calls[0]["prompt"] == "Q?"
    assert tool.to_openai_schema()["function"]["name"] == "describe_image"
    assert tool.to_gemini_schema()["name"] == "describe_image"


def test_tool_end_to_end_with_gemini_provider_mocked_network(tmp_path):
    payload = {"candidates": [{"content": {"parts": [{"text": "A tiny test image."}]}}]}
    provider = GeminiVisionProvider(api_key="k", model="gemini-test")
    config, _, root = _make(tmp_path, provider=provider)
    (root / "a.webp").write_bytes(WEBP)
    with patch("ragleap_tools.vision.urllib.request.urlopen", return_value=_fake_response(payload)):
        result = make_vision_tool(config).call(path="a.webp")
    assert result.success is True
    assert result.result == {"description": "A tiny test image."}
