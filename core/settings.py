"""Dashboard-editable settings: a dashboard value wins, else the environment (.env), else the default.

Secrets (API keys) are encrypted at rest with Fernet (ADDON_ENCRYPTION_KEY) and are write-only
through the API: callers only ever learn whether a secret is set. Only whitelisted names can be stored.
"""
import logging
import os
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)



def get_connection():
    # Own helper (no core.employees import): core.embedding imports this module, and the
    # employees package imports core.embedding, so importing it here would be circular.
    import psycopg2
    return psycopg2.connect(os.environ.get("DATABASE_URL", "postgresql://ragleap:ragleap@localhost:5432/ragleap_core"))


CACHE_SECONDS = 5.0
MAX_VALUE_LENGTH = 512
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_lock = threading.Lock()
_cache = {"at": -1e9, "rows": {}}


def _spec() -> Dict[str, bool]:
    """Settable names -> is_secret. Built lazily from the real provider tables."""
    from core.embedding import OPENAI_COMPATIBLE
    from core.generation import PROVIDER_BASE_URLS
    spec = {name: False for name in (
        "LLM_PROVIDER", "LLM_FALLBACK_PROVIDERS", "GEMINI_CHAT_MODEL", "GEMINI_EMBEDDING_MODEL",
        "EMBEDDING_PROVIDER", "EMBEDDING_DIMENSIONS", "ANTHROPIC_MODEL")}
    spec["GEMINI_API_KEY"] = True
    spec["ANTHROPIC_API_KEY"] = True
    for p in PROVIDER_BASE_URLS:
        up = p.upper()
        spec[up + "_API_KEY"] = True
        spec[up + "_MODEL"] = False
        spec[up + "_BASE_URL"] = False
    for p in OPENAI_COMPATIBLE:
        up = p.upper()
        spec[up + "_API_KEY"] = True
        spec[up + "_BASE_URL"] = False
        spec[up + "_EMBEDDING_MODEL"] = False
    return spec


def llm_providers() -> List[str]:
    from core.generation import PROVIDER_BASE_URLS
    return ["gemini", "anthropic"] + list(PROVIDER_BASE_URLS)


def embedding_providers() -> List[str]:
    from core.embedding import OPENAI_COMPATIBLE
    return ["gemini"] + list(OPENAI_COMPATIBLE)


def invalidate() -> None:
    with _lock:
        _cache["at"] = -1e9


def _rows() -> Dict[str, Tuple[str, bool]]:
    now = time.monotonic()
    with _lock:
        if now - _cache["at"] < CACHE_SECONDS:
            return _cache["rows"]
    rows: Dict[str, Tuple[str, bool]] = {}
    try:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT key, value, is_secret FROM app_settings")
            rows = {k: (v, bool(s)) for k, v, s in cur.fetchall()}
            cur.close()
        finally:
            conn.close()
    except Exception as e:  # table missing or database down: fall back to the environment
        logger.debug("Dashboard settings unavailable: %s", type(e).__name__)
    with _lock:
        _cache["rows"] = rows
        _cache["at"] = now
    return rows


def _fernet():
    raw = os.environ.get("ADDON_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(raw.encode())
    except Exception:
        return None


def get(name: str, default: str = "") -> str:
    row = _rows().get(name)
    if row is not None:
        stored, secret = row
        if not secret:
            return stored
        f = _fernet()
        if f is not None:
            try:
                return f.decrypt(stored.encode()).decode()
            except Exception:
                logger.warning("A stored secret could not be decrypted (ADDON_ENCRYPTION_KEY changed?)")
    env_value = os.environ.get(name)
    return env_value if env_value is not None else default


def source(name: str) -> str:
    if name in _rows():
        return "dashboard"
    return "env" if os.environ.get(name, "").strip() else "default"


def _validate(name: str, raw) -> str:
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise ValueError("Setting values must be text or numbers.")
    value = str(raw).strip()
    if len(value) > MAX_VALUE_LENGTH or _CONTROL_CHARS.search(value):
        raise ValueError("Invalid value: too long or contains control characters.")
    if name in ("LLM_PROVIDER", "EMBEDDING_PROVIDER"):
        value = value.lower()
        allowed = llm_providers() if name == "LLM_PROVIDER" else embedding_providers()
        if value not in allowed:
            raise ValueError("Unknown provider for " + name + ".")
    elif name == "LLM_FALLBACK_PROVIDERS":
        parts = [p.strip().lower() for p in value.split(",") if p.strip()]
        if any(p not in llm_providers() for p in parts):
            raise ValueError("Unknown provider in LLM_FALLBACK_PROVIDERS.")
        value = ",".join(parts)
    elif name == "EMBEDDING_DIMENSIONS":
        if not value.isdigit() or not 1 <= int(value) <= 16000:
            raise ValueError("EMBEDDING_DIMENSIONS must be a whole number from 1 to 16000.")
    elif name.endswith("_BASE_URL"):
        if not re.match(r"^https?://\S+$", value):
            raise ValueError(name + " must start with http:// or https://")
    return value


def set_many(updates: Dict[str, Optional[object]]) -> List[str]:
    """Validate everything first, then write atomically. None or blank removes the dashboard value."""
    spec = _spec()
    clean: Dict[str, Optional[str]] = {}
    for name, raw in updates.items():
        if name not in spec:
            raise ValueError("Unknown setting.")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            clean[name] = None
        else:
            clean[name] = _validate(name, raw)
    f = None
    if any(spec[n] and v is not None for n, v in clean.items()):
        f = _fernet()
        if f is None:
            raise ValueError("ADDON_ENCRYPTION_KEY is not set, so secrets cannot be stored.")
    conn = get_connection()
    try:
        cur = conn.cursor()
        for name, value in clean.items():
            if value is None:
                cur.execute("DELETE FROM app_settings WHERE key = %s", (name,))
            else:
                secret = spec[name]
                stored = f.encrypt(value.encode()).decode() if secret else value
                cur.execute(
                    "INSERT INTO app_settings (key, value, is_secret, updated_at) VALUES (%s, %s, %s, now()) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
                    "is_secret = EXCLUDED.is_secret, updated_at = now()",
                    (name, stored, secret))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    invalidate()
    return sorted(clean)


def describe() -> List[Dict]:
    """Every settable name with its source. Secret values are never included."""
    spec = _spec()
    out = []
    for name in sorted(spec):
        current = get(name)
        item = {"name": name, "secret": spec[name], "is_set": bool(current), "source": source(name)}
        if not spec[name]:
            item["value"] = current
        out.append(item)
    return out
