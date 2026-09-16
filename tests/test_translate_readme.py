"""
Tests for scripts/translate_readme.py's resumability logic (state
loading/saving, skip-if-up-to-date). Mocks the Gemini client entirely --
no real API calls, no quota cost.
"""
import hashlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Other test files in this suite (test_bigquery_connector.py,
# test_gmail_connector.py) replace sys.modules['google'] with a MagicMock
# at import time to stub a heavy optional dependency, with no cleanup -
# this leaks into any test running later in the same pytest process and
# breaks a real `import google.genai`, which is what translate_readme.py
# needs. Same protective pattern as tests/test_embedding.py: capture the
# REAL google.genai modules once, here at collection time, forcing one
# real import if needed.
_saved_at_collection = {k: v for k, v in sys.modules.items() if k == "google" or k.startswith("google.")}
for _k in list(_saved_at_collection):
    del sys.modules[_k]
import google.genai  # noqa: F401 - forces one real import, now cached below
_REAL_GOOGLE_MODULES = {k: v for k, v in sys.modules.items() if k == "google" or k.startswith("google.")}

# Unlike core/embedding.py (which imports google.genai lazily, inside a
# function), scripts/translate_readme.py imports it at module top level -
# so the real modules must be present in sys.modules for this one import
# statement. Once imported, translate_readme's own `genai`/`types` names
# hold direct references to the real module objects regardless of later
# sys.modules changes -- so we can safely restore the ambient (possibly
# stubbed-by-another-test-file) state immediately after, rather than
# leaving real modules installed for the rest of collection/other files
# (which would break e.g. test_bigquery_connector.py's own stub for when
# ITS tests run later -- collection finishes for all files before any
# test function executes).
for _k in list(sys.modules):
    if _k == "google" or _k.startswith("google."):
        del sys.modules[_k]
sys.modules.update(_REAL_GOOGLE_MODULES)
import translate_readme
for _k in list(sys.modules):
    if _k == "google" or _k.startswith("google."):
        del sys.modules[_k]
sys.modules.update(_saved_at_collection)


@pytest.fixture(autouse=True)
def _real_google_genai_import():
    """Swap in the real, pre-imported google.genai modules before each
    test, and restore prior state after - see the module-level comment
    above for why this is needed."""
    saved = {k: v for k, v in sys.modules.items() if k == "google" or k.startswith("google.")}
    for k in list(saved):
        del sys.modules[k]
    sys.modules.update(_REAL_GOOGLE_MODULES)
    yield
    for k in list(sys.modules):
        if k == "google" or k.startswith("google."):
            del sys.modules[k]
    sys.modules.update(saved)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")
    monkeypatch.setattr(translate_readme.time, "sleep", lambda *_: None)
    with open("README.md", "w", encoding="utf-8") as f:
        f.write("# Test README\n\nSome content.\n")
    return tmp_path


def test_load_state_missing_file_returns_empty(workdir):
    assert translate_readme.load_state() == {}


def test_save_and_load_state_roundtrip(workdir):
    translate_readme.save_state({"af": "somehash"})
    assert translate_readme.load_state() == {"af": "somehash"}


def test_skips_language_already_up_to_date(workdir):
    with open("README.md", encoding="utf-8") as f:
        source_hash = hashlib.sha256(f.read().encode("utf-8")).hexdigest()

    os.makedirs("readmes", exist_ok=True)
    with open("readmes/README.af.md", "w", encoding="utf-8") as f:
        f.write("# Toets Leesmy\n")
    translate_readme.save_state({"af": source_hash})

    mock_response = MagicMock()
    mock_response.text = "MOCK TRANSLATION"
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch.object(translate_readme.genai, "Client", return_value=mock_client):
        translate_readme.main()

    # 'af' was already up to date -- must NOT have been re-translated
    call_args_list = mock_client.models.generate_content.call_args_list
    for call in call_args_list:
        assert "Afrikaans" not in call.kwargs.get("contents", "")

    with open("readmes/README.af.md", encoding="utf-8") as f:
        assert f.read() == "# Toets Leesmy\n"  # untouched


def test_translates_missing_language_and_updates_state(workdir):
    mock_response = MagicMock()
    mock_response.text = "MOCK TRANSLATION"
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch.object(translate_readme.genai, "Client", return_value=mock_client):
        translate_readme.main()

    assert os.path.exists("readmes/README.af.md")
    with open("readmes/README.af.md", encoding="utf-8") as f:
        assert f.read() == "MOCK TRANSLATION\n"

    state = translate_readme.load_state()
    with open("README.md", encoding="utf-8") as f:
        expected_hash = hashlib.sha256(f.read().encode("utf-8")).hexdigest()
    assert state["af"] == expected_hash
    assert len(state) == len(translate_readme.TARGET_LANGUAGES)


def test_quota_exhaustion_exits_zero_not_one(workdir, capsys):
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception(
        "429 RESOURCE_EXHAUSTED. quota exceeded"
    )

    with patch.object(translate_readme.genai, "Client", return_value=mock_client):
        translate_readme.main()  # must NOT raise SystemExit(1)

    captured = capsys.readouterr()
    assert "quota" in captured.out.lower() or "transient" in captured.out.lower()


def test_real_failure_exits_one(workdir):
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("totally unexpected error")

    with patch.object(translate_readme.genai, "Client", return_value=mock_client):
        with pytest.raises(SystemExit) as exc_info:
            translate_readme.main()
        assert exc_info.value.code == 1
