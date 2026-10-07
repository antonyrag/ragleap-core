from pathlib import Path

JS = (Path(__file__).resolve().parent.parent / "core" / "office_static" / "app.js").read_text()


def test_login_link_is_read_stored_and_removed_from_the_address_bar():
    assert "location.hash" in JS and "#key=" in JS
    stored = JS.index('sessionStorage.setItem("ragleap_key", linkKey)')
    cleaned = JS.index('history.replaceState(null, "", location.pathname + location.search)')
    reads = JS.index('let key = sessionStorage.getItem("ragleap_key")')
    assert stored < cleaned < reads


def test_login_link_never_uses_local_storage_or_the_server():
    assert "localStorage" not in JS
    start = JS.index("const linkKey")
    block = JS[start:JS.index('let key = sessionStorage')]
    assert "fetch(" not in block and "api(" not in block
