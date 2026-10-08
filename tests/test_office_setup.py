from pathlib import Path

JS = (Path(__file__).resolve().parent.parent / "core" / "office_static" / "app.js").read_text()


def test_setup_tab_exists_and_is_first():
    assert 'const TABS = [["setup", "Setup"], ["overview", "Overview"]' in JS


def test_setup_tab_uses_the_status_endpoint():
    assert '"/setup/status"' in JS and 'tab === "setup"' in JS


def test_page_opens_on_setup_only_when_something_required_is_missing():
    assert 'if (!s.ready) tab = "setup"' in JS


def test_setup_tab_can_jump_to_settings():
    assert 'it.fix === "settings"' in JS and 'tab = "settings"' in JS
