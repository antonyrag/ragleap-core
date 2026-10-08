"""ragleap_agents.state - where a paused run lives between run() and resume().

A run's state is a plain JSON-safe dict, so any store that can keep a string
works (a file, Redis, a database row). The library ships only the in-memory
store; it owns no database.

Concurrency: InMemoryStateStore serialises its own calls with a lock, but
resume() is load -> check -> save, which is not atomic across processes. If
several workers can resume the same run, give your store an atomic
compare-and-set (or a row lock) around that sequence.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, Optional, Protocol


class StateStore(Protocol):
    def save(self, run_id: str, state: Dict[str, Any]) -> None: ...

    def load(self, run_id: str) -> Optional[Dict[str, Any]]: ...


class InMemoryStateStore:
    """Keeps states as JSON text, so anything that cannot be serialised
    fails here, in development, and not in a real database later."""

    def __init__(self) -> None:
        self._data: Dict[str, str] = {}
        self._lock = threading.Lock()

    def save(self, run_id: str, state: Dict[str, Any]) -> None:
        text = json.dumps(state)
        with self._lock:
            self._data[run_id] = text

    def load(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            text = self._data.get(run_id)
        return None if text is None else json.loads(text)
