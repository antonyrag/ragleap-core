"""
Tool registry for AI Employee actions.

A first, deliberately narrow step toward a real tool-calling architecture
(see ROADMAP.md's 9-pattern agentic audit): a single place that maps a
tool name to what it does, its parameter shape, and whether it requires
autonomy approval -- instead of each channel router hand-rolling its own
copy of the same dispatch logic.

Registering a tool here does not change WHETHER it can act -- that is
still entirely governed by core.autonomy.execute_or_request()'s mode/
allowlist gates, same as before. This registry only removes duplication
in HOW a tool is invoked from multiple call sites.

First (and currently only) entry: escalate_to_owner, migrated from the
near-identical inline blocks that previously existed separately in
channels/telegram/router.py, channels/whatsapp/router.py, and
channels/discord/router.py. Behavior is unchanged -- same detection,
same dispatch, same fallback -- this just consolidates it.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from core.employees.triggers import detect_escalation_request


@dataclass
class Tool:
    """
    name: registry key, also the action_type passed to
        core.autonomy.execute_or_request() where applicable.
    description: human-readable summary -- also intended for future
        LLM-driven tool-calling (chain-of-thought / orchestration work
        later in the 9-pattern build), not just documentation.
    parameters: JSON-schema-style parameter spec. Not yet consumed by
        anything (no LLM tool-calling exists yet) -- present now so
        later patterns can describe tools without a breaking change to
        this dataclass's shape.
    handler: the actual callable. Signature intentionally loose
        (**kwargs) since different tools will need different inputs;
        each handler documents its own expected kwargs.
    requires_approval: documents (does not enforce) that this tool's
        real gating happens inside execute_or_request()'s mode/allowlist
        logic, not here. Present for future tools that might bypass
        execute_or_request() entirely and need their own approval note.
    """
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Optional[Dict]]
    requires_approval: bool = True


def _handle_escalate_to_owner(channel: str, target: str, message_text: str) -> Optional[Dict]:
    """
    Detects an explicit request for a human (fixed phrase match, see
    core.employees.triggers.detect_escalation_request) and, if detected,
    dispatches an escalate_to_owner action via
    core.autonomy.execute_or_request() -- same mode/allowlist gating as
    every other autonomous action.

    Returns None if no escalation was detected (caller should fall
    through to a normal answer). Returns execute_or_request()'s result
    dict if an escalation was detected and dispatched -- caller checks
    result["status"] in ("executed", "pending_approval") to decide
    whether to short-circuit with the "flagged for a team member" reply.

    Imports core.autonomy lazily (matching the existing convention
    inside core.autonomy itself, which lazily imports
    core.employees.defaults) to avoid a core.autonomy <-> core.employees
    import-order issue.
    """
    if not detect_escalation_request(message_text):
        return None

    from core.autonomy import execute_or_request
    return execute_or_request(
        action_type="escalate_to_owner", channel=channel, target=target,
        content=f"Customer asked to speak with a human.\nMessage: {message_text}",
        subject="Escalation request",
    )


TOOL_REGISTRY: Dict[str, Tool] = {
    "escalate_to_owner": Tool(
        name="escalate_to_owner",
        description=(
            "Detects an explicit request to speak with a human (fixed "
            "phrase match, not an LLM judgment call) and, if the "
            "owner's autonomy settings allow it, notifies the owner "
            "via the configured approval channel."
        ),
        parameters={
            "channel": {"type": "string", "description": "Channel the message came in on, e.g. 'telegram'"},
            "target": {"type": "string", "description": "Channel-specific recipient id, e.g. a chat_id or phone number"},
            "message_text": {"type": "string", "description": "The customer's raw message"},
        },
        handler=_handle_escalate_to_owner,
        requires_approval=True,
    ),
}
