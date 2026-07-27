"""
Guardrail hooks for ragleap-rag - user-supplied validation callbacks
for ingested content (input_guardrails) and generated answers
(output_guardrails). This extends the existing sanitization module
(null-byte stripping, injection-risk heuristics) rather than
replacing it - guardrails run in addition to, after, that baseline.

Honest scope: for ask_stream(), output guardrails can only run AFTER
the full answer has been assembled - by then, individual tokens have
already been yielded to the caller. A GuardrailViolation raised during
streaming is logged as a warning, not silently enforced, since
already-streamed content cannot be retroactively un-sent. Guardrails
are fully enforced (block before the caller sees anything) only for
the non-streaming ask().
"""
import logging
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


class GuardrailViolation(Exception):
    """Raise this from a guardrail callable to reject content.
    For input_guardrails, this aborts ingestion - nothing is stored.
    For output_guardrails on ask() (not ask_stream()), this replaces
    the answer with a refusal message before it's returned."""


def run_guardrails(text: str, guardrails: Optional[List[Callable[[str], str]]]) -> str:
    """Run each guardrail callable in order, threading the (possibly
    modified) text through each one. A guardrail can either return a
    (possibly transformed) string, or raise GuardrailViolation to
    reject the content outright."""
    if not guardrails:
        return text
    for guardrail in guardrails:
        text = guardrail(text)
    return text
