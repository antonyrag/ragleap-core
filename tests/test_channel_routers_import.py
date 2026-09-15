"""
Smoke test: each channel router module must import cleanly.

No test previously imported any channels/*/router.py module at all, which
let a real bug slip through: channels/voice/router.py referenced
TOOL_REGISTRY at runtime without importing it (a NameError waiting to
happen the first time a caller escalated), and the full test suite still
passed because nothing exercised the import. This test would have caught
it immediately, before any runtime path was needed.

All 4 routers use os.environ.get(...) (never os.environ[...]) for their
config at module level, so a bare import is safe without any env vars
set -- confirmed by inspection before writing this test.
"""
import importlib


def test_telegram_router_imports_cleanly():
    importlib.import_module("channels.telegram.router")


def test_whatsapp_router_imports_cleanly():
    importlib.import_module("channels.whatsapp.router")


def test_discord_router_imports_cleanly():
    importlib.import_module("channels.discord.router")


def test_voice_router_imports_cleanly():
    importlib.import_module("channels.voice.router")


def test_all_channel_routers_reference_tool_registry():
    """
    All 4 channels now dispatch escalate_to_owner via the same registry
    entry (core.employees.tools.TOOL_REGISTRY) rather than duplicated
    inline logic -- verifies the module actually has the attribute
    imported, not just that Python didn't error on import.
    """
    for module_name in (
        "channels.telegram.router",
        "channels.whatsapp.router",
        "channels.discord.router",
        "channels.voice.router",
    ):
        module = importlib.import_module(module_name)
        assert hasattr(module, "TOOL_REGISTRY")
        assert "escalate_to_owner" in module.TOOL_REGISTRY
