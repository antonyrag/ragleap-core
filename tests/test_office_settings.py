from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "core" / "office_static"


def test_settings_tab_uses_the_settings_endpoints():
    js = (STATIC / "app.js").read_text()
    for token in ('["settings", "Settings"]', '"/settings"', '"/settings/test/llm"',
                  '"/settings/test/embedding"', '"PUT"'):
        assert token in js, token


def test_secret_inputs_are_password_fields_and_never_prefilled():
    js = (STATIC / "app.js").read_text()
    assert 'it.secret ? "password" : "text"' in js
    assert "if (!it.secret) el.value" in js
    assert "localStorage" not in js


def test_lock_clears_the_settings_form():
    js = (STATIC / "app.js").read_text()
    assert "    settingsEl = null;\n" in js
