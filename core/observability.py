"""
Observability/tracing for RagLeap Core -- item #2 of the 9-pattern
agentic-architecture build (see ROADMAP.md's agentic audit).

Deliberately narrow, matching the Tool Registry's (core/employees/tools.py)
first-entry approach: a flat per-request trace record for the blocking
chat pipeline (core.chat.ask()) written to the agent_traces table, NOT a
formal span/tree/distributed-tracing layer. Tracing is best-effort and
must never break the actual chat response -- record_trace() catches and
logs its own failures rather than raising, same philosophy as
core/employees/memory.py's write_learned_skill().

core.chat.ask_stream() is deliberately NOT traced here. It's a plain
pass-through generator (`yield from generator.generate_answer_stream()`)
with no final-usage capture at the ask_stream() layer at all -- per its
own docstring, "Sources/chunks_used/detected_language aren't available
until generation completes." Tracing it properly would need
generate_answer_stream()'s internal result_holder mechanism threaded
through to ask_stream() and consumed after the yield-from completes --
a real, separate piece of work, not something to bolt on blind here.

Also strengthens the audit story for the still-open compliance questions
on the 7 sensitive-domain roles (see ROADMAP.md's "Vision: Vertical AI
Employees" section) -- a real trace of what a legal_intake/healthcare/etc
role actually answered, when, and with what retrieval context.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from core.employees._db import get_connection

logger = logging.getLogger(__name__)


def record_trace(
    query: str,
    role: Optional[str] = None,
    detected_language: Optional[str] = None,
    chunks_retrieved: Optional[int] = None,
    chunks_sent: Optional[int] = None,
    provider_used: Optional[str] = None,
    fallback_used: bool = False,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> bool:
    """
    Insert one row into agent_traces for a completed (or failed) call to
    core.chat.ask(). Best-effort: catches and logs its own failures
    (warning level, matching the visibility fix in PR #341) rather than
    raising, so a tracing failure never takes down the actual chat
    response. Returns True on success, False on failure.
    """
    try:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO agent_traces "
                "(role, query, detected_language, chunks_retrieved, chunks_sent, "
                "provider_used, fallback_used, prompt_tokens, completion_tokens, "
                "total_tokens, latency_ms, error) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    role, query, detected_language, chunks_retrieved, chunks_sent,
                    provider_used, fallback_used, prompt_tokens, completion_tokens,
                    total_tokens, latency_ms, error,
                ),
            )
            conn.commit()
            cur.close()
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to record agent trace (non-fatal): {e}")
        return False


def generate_observability_report() -> str:
    """
    Real, unfiltered aggregation of today's agent_traces -- total
    requests, error rate, average latency, and a breakdown by role and
    by provider_used. Matches the style of
    core.autonomy.generate_autonomy_daily_report(): today-scoped, plain
    formatted string, no config-change side effects.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, provider_used, fallback_used, latency_ms, error "
            "FROM agent_traces WHERE created_at >= CURRENT_DATE"
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        return f"Report generation error: {e}"
    finally:
        conn.close()

    if not rows:
        return "Observability Report - No traced requests today."

    total = len(rows)
    errors = sum(1 for _, _, _, _, error in rows if error)
    fallbacks = sum(1 for _, _, fallback_used, _, _ in rows if fallback_used)
    latencies = [lat for _, _, _, lat, _ in rows if lat is not None]
    avg_latency = sum(latencies) / len(latencies) if latencies else None

    by_role: Dict[str, int] = {}
    by_provider: Dict[str, int] = {}
    for role, provider_used, _, _, _ in rows:
        by_role[role or "(no role)"] = by_role.get(role or "(no role)", 0) + 1
        by_provider[provider_used or "(unknown)"] = by_provider.get(provider_used or "(unknown)", 0) + 1

    lines = [f"Observability Report - {datetime.now(timezone.utc).date().isoformat()}", ""]
    lines.append(f"Total traced requests: {total}")
    lines.append(f"Errors: {errors} ({100 * errors / total:.1f}%)")
    lines.append(f"Fallback provider used: {fallbacks} ({100 * fallbacks / total:.1f}%)")
    if avg_latency is not None:
        lines.append(f"Average latency: {avg_latency:.0f}ms")
    lines.append("")
    lines.append("By role:")
    for role, count in sorted(by_role.items(), key=lambda kv: -kv[1]):
        lines.append(f"  - {role}: {count}")
    lines.append("")
    lines.append("By provider:")
    for provider, count in sorted(by_provider.items(), key=lambda kv: -kv[1]):
        lines.append(f"  - {provider}: {count}")

    return "\n".join(lines)
