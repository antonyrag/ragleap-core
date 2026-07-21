"""
Content sanitization and injection-risk detection for ragleap-rag.

Honest scope: this reduces risk, it does not eliminate it. Prompt
injection via retrieved content is an open research problem with no
complete solution at the library level - a sufficiently motivated
attacker can still craft content that evades pattern-based detection.
What this module does provide:

1. Character-level sanitization - strips null bytes, control
   characters, and invisible/zero-width Unicode characters, a
   documented technique for hiding instructions inside text that
   looks normal to a human reviewer.
2. Heuristic injection-pattern detection - flags common trigger
   phrases at ingest time. This is pattern matching, not semantic
   understanding, and will miss novel or obfuscated attempts. Treat
   flagged content as a signal to review, not a guarantee of safety.
3. A basic length guard against abuse via extremely long single chunks.
"""
import logging
import re
import unicodedata
from typing import List

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHUNK_LENGTH = 50_000

# Common prompt-injection trigger phrases. Heuristic, not exhaustive -
# a determined attacker can rephrase around any fixed list.
INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior|above) instructions",
    r"disregard (all )?(previous|prior|above) instructions",
    r"you are now",
    r"new instructions:",
    r"system prompt:",
    r"\bsystem:\s",
    r"forget (everything|all) (you|that)",
    r"reveal your (system prompt|instructions)",
    r"act as if",
    r"do not (follow|obey) (your|the) (previous|original) instructions",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def sanitize_text(text: str) -> str:
    """
    Strip null bytes, control characters (except newline/tab), and
    invisible/zero-width Unicode characters. Safe to call on any text -
    normal content is unaffected.
    """
    if not text:
        return text

    # Remove null bytes and most control characters, but keep \n and \t
    cleaned = "".join(
        ch for ch in text
        if ch in ("\n", "\t") or unicodedata.category(ch) not in ("Cc", "Cf")
    )
    return cleaned


def detect_injection_risk(text: str) -> List[str]:
    """
    Return a list of matched suspicious phrases, if any. Empty list
    means no known pattern matched - not a guarantee the content is
    safe, just that it didn't match this heuristic list.
    """
    if not text:
        return []

    matches = []
    for pattern in _COMPILED_PATTERNS:
        found = pattern.search(text)
        if found:
            matches.append(found.group(0))
    return matches


def check_length(text: str, max_length: int = DEFAULT_MAX_CHUNK_LENGTH) -> bool:
    """Return True if text is within the allowed length."""
    return len(text) <= max_length
