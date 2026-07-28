"""
Lightweight observability hooks for ragleap-rag - fire-and-forget
event emission points that other tools (logging, metrics, tracing,
or a future ragleap-observability package) can consume. This module
does NOT implement any dashboard, storage, or analysis itself - it
is purely the instrumentation seam.

Design philosophy: a broken or slow hook must never break the actual
RAG operation. Every hook call is wrapped in try/except - an
exception in a hook is logged as a warning and swallowed, never
propagated. This is fire-and-forget, not a guarantee of delivery.
"""
import logging
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def fire_event(event: Dict, handlers: Optional[List[Callable[[Dict], None]]], hook_name: str) -> None:
    """Call each handler with the event dict, in order. A handler
    raising an exception is logged and swallowed - never propagated,
    since observability must never break the actual RAG operation."""
    if not handlers:
        return
    for handler in handlers:
        try:
            handler(event)
        except Exception as e:
            logger.warning(f"Observability hook '{hook_name}' raised an exception (swallowed): {e}")
