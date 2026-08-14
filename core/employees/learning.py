"""Write path: every learn_from_* entry point + auto_learn_from_all, ported from skill_context.py."""
import logging

from core.employees import memory, profile
from core.employees._db import get_connection

logger = logging.getLogger(__name__)


def learn_from_owner_instruction(instruction_text: str):
    if not instruction_text or len(instruction_text.strip()) < 10:
        return
    memory.write_learned_skill(
        text="OWNER INSTRUCTION (always follow this): " + instruction_text.strip(),
        tags=["owner_instruction", "core", "business"], importance=1.0,
        source="owner", permanent=True,
    )
    auto_learn_from_all()


def learn_from_conversation(channel, user_message, ai_reply, resolved=True, score=0.7):
    if not resolved or score < 0.5:
        return
    text = (f"[{channel.upper()} INTERACTION — score {score:.1f}]\n"
            f"Customer said: {user_message[:300]}\nAI replied: {ai_reply[:300]}")
    memory.write_learned_skill(text=text, tags=["learned_pattern", "interaction", channel, "comms"],
                                importance=min(score, 0.85), source="conversation")


def learn_from_owner_approval(action_type, action_detail, outcome):
    text = f"OWNER APPROVED ACTION [{action_type}]: {action_detail[:300]}\nOutcome: {outcome[:200]}"
    memory.write_learned_skill(text=text, tags=["learned_pattern", "approval", "owner_approved", action_type],
                                importance=0.95, source="owner_approval", permanent=True)


def learn_from_lead_capture(lead_info, channel):
    text = f"LEAD CAPTURED via {channel}: Customer profile: {str(lead_info)[:300]}"
    memory.write_learned_skill(text=text, tags=["lead", "sales", "learned_pattern", channel],
                                importance=0.75, source="lead_capture")


def learn_from_email_handled(subject, summary, action_taken):
    text = (f"EMAIL HANDLED: Subject: {subject[:100]}\nSummary: {summary[:200]}\n"
            f"Action taken: {action_taken[:200]}")
    memory.write_learned_skill(text=text, tags=["mail", "secretary", "comms", "learned_pattern"],
                                importance=0.7, source="email")


def learn_from_integration_action(integration_name, action, result):
    text = f"INTEGRATION ACTION: {integration_name} — {action[:150]}\nResult: {result[:200]}"
    memory.write_learned_skill(text=text, tags=["integration", "operations", "process", "capability"],
                                importance=0.75, source="integration")


def learn_from_voice_call(transcript_summary, outcome, language):
    text = f"VOICE CALL [{language}]: {transcript_summary[:300]}\nOutcome: {outcome}"
    memory.write_learned_skill(text=text, tags=["voice", "support", "learned_pattern", "comms"],
                                importance=0.72, source="voice_call")


def auto_learn_from_all():
    try:
        prof = profile.get_profile()
        parts = []
        if prof.get("description"):
            parts.append("BUSINESS DESCRIPTION (owner-defined):\n" + prof["description"])
        if prof.get("products_services"):
            parts.append("PRODUCTS / SERVICES:\n" + prof["products_services"])
        if prof.get("target_customers"):
            parts.append("TARGET CUSTOMERS:\n" + prof["target_customers"])
        if prof.get("working_hours"):
            parts.append("WORKING HOURS: " + prof["working_hours"])
        if prof.get("location"):
            parts.append("LOCATION: " + prof["location"])
        if prof.get("tone_preference"):
            parts.append("COMMUNICATION TONE: " + prof["tone_preference"])
        if prof.get("primary_language"):
            parts.append("PRIMARY LANGUAGE: " + prof["primary_language"])
        if prof.get("owner_instructions"):
            parts.append("OWNER INSTRUCTIONS (always obey these):\n" + prof["owner_instructions"])

        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT text FROM chunks ORDER BY created_at DESC LIMIT 15")
            chunk_texts = [row[0][:200] for row in cur.fetchall() if row[0]]
            if chunk_texts:
                parts.append("FROM UPLOADED DOCUMENTS:\n" + "\n---\n".join(chunk_texts[:8]))
            try:
                cur.execute("SELECT name FROM data_sources WHERE is_active = true")
                names = [row[0] for row in cur.fetchall()]
                if names:
                    parts.append("ACTIVE INTEGRATIONS: " + ", ".join(names))
            except Exception as e:
                logger.debug(f"data_sources read error (non-fatal): {e}")
            cur.close()
        finally:
            conn.close()

        recent = memory.tag_search(["learned_pattern", "approval", "lead", "mail", "voice"], top_k=10)
        recent = [r for r in recent if r.get("importance", 0) >= 0.75]
        if recent:
            learned_texts = [r.get("summary") or r["text_content"][:150] for r in recent]
            parts.append("RECENTLY LEARNED:\n" + "\n".join(learned_texts))

        if not parts:
            return
        learned_text = "\n\n".join(parts)
        profile.save_auto_learned(learned_text)
        memory.write_learned_skill(text=learned_text[:2000], tags=["business", "identity", "auto_learned", "core"],
                                    importance=0.95, source="auto_learn", permanent=True, force_update=True)
    except Exception as e:
        logger.error(f"auto_learn_from_all error: {e}")
