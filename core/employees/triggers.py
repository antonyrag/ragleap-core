"""
Deterministic triggers that let a role's response automatically dispatch
an autonomous action via core.autonomy.execute_or_request() -- respecting
whatever mode/allowlists the owner has configured (default: off, meaning
this changes nothing until the owner explicitly opts in via
/autonomy/configure).

No LLM judgment call here on purpose, matching the rest of the
Autonomous Loop's design: a fixed, auditable phrase match, not a model
deciding on its own whether to escalate. That keeps every trigger fully
predictable and reviewable, the same way autonomy.py's mode/allowlist
gates are.

Deliberately narrow for a first version: one trigger (explicit request
for a human), one action_type ("escalate_to_owner"). More triggers are
a natural follow-up once this pattern is proven in real use, not
something to guess at speculatively here.
"""
import logging

logger = logging.getLogger(__name__)

ESCALATION_PHRASES = {
    "talk to a human", "speak to a human", "speak to someone",
    "talk to someone", "real person", "human agent", "human support",
    "this isn't helping", "this is not helping", "not what i need",
    "let me speak to a person", "connect me to a person",
}


def detect_escalation_request(message: str) -> bool:
    """
    True if the message explicitly asks for human help, using a fixed
    phrase match -- not an LLM judgment call. Deliberately conservative:
    a missed real escalation request is safer here than escalating a
    routine question by mistake.
    """
    if not message:
        return False
    normalized = message.strip().lower()
    return any(phrase in normalized for phrase in ESCALATION_PHRASES)
