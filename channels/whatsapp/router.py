"""
WhatsApp channel adapter for RagLeap Core.

Receives WhatsApp messages via Twilio or Gupshup webhooks, answers them
using the core RAG pipeline (core.chat.ask), and sends the response back.
Single-tenant: one bot, one document set, configured entirely via .env.
No workspace concept, no Manager AI, no lead capture — just document Q&A
over WhatsApp.
"""
import os
import hmac
import hashlib
import base64
import logging

import requests

from core.chat import ask
from core.workflows import call_n8n_workflows

logger = logging.getLogger(__name__)

WHATSAPP_PROVIDER = os.environ.get("WHATSAPP_PROVIDER", "twilio").lower()

# Twilio config
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER")

# Gupshup config
GUPSHUP_API_KEY = os.environ.get("GUPSHUP_API_KEY")
GUPSHUP_APP_NAME = os.environ.get("GUPSHUP_APP_NAME")
GUPSHUP_SOURCE_NUMBER = os.environ.get("GUPSHUP_SOURCE_NUMBER")

MAX_WHATSAPP_MESSAGE_LENGTH = 4096


def _verify_twilio_signature(url: str, params: dict, signature: str) -> bool:
    """Verify a Twilio webhook request using HMAC-SHA1, per Twilio's official algorithm."""
    if not signature or not TWILIO_AUTH_TOKEN:
        return False

    full_url = url
    for key in sorted(params.keys()):
        full_url += key + params[key]

    computed = base64.b64encode(
        hmac.new(TWILIO_AUTH_TOKEN.encode("utf-8"), full_url.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")

    return hmac.compare_digest(computed, signature)


def send_whatsapp_message(to_phone: str, message_text: str) -> bool:
    """Send a WhatsApp message via the configured provider (Twilio or Gupshup)."""
    if len(message_text) > MAX_WHATSAPP_MESSAGE_LENGTH:
        message_text = message_text[:MAX_WHATSAPP_MESSAGE_LENGTH - 20] + "...\n(truncated)"

    if WHATSAPP_PROVIDER == "gupshup":
        return _send_via_gupshup(to_phone, message_text)
    return _send_via_twilio(to_phone, message_text)


def _send_via_twilio(to_phone: str, message_text: str) -> bool:
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
        logger.error("Twilio credentials not configured — set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER in .env")
        return False

    to_formatted = to_phone if to_phone.startswith("whatsapp:") else f"whatsapp:{to_phone}"
    from_formatted = TWILIO_WHATSAPP_NUMBER if TWILIO_WHATSAPP_NUMBER.startswith("whatsapp:") else f"whatsapp:{TWILIO_WHATSAPP_NUMBER}"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    response = requests.post(
        url,
        data={"From": from_formatted, "To": to_formatted, "Body": message_text},
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=30,
    )

    if response.status_code == 201:
        logger.info(f"Twilio: message sent to {to_phone}")
        return True

    logger.error(f"Twilio send failed: {response.status_code} {response.text}")
    return False


def _send_via_gupshup(to_phone: str, message_text: str) -> bool:
    import json as _json

    if not all([GUPSHUP_API_KEY, GUPSHUP_APP_NAME, GUPSHUP_SOURCE_NUMBER]):
        logger.error("Gupshup credentials not configured — set GUPSHUP_API_KEY, GUPSHUP_APP_NAME, GUPSHUP_SOURCE_NUMBER in .env")
        return False

    clean_to = to_phone.replace("whatsapp:", "").replace("+", "")
    clean_from = GUPSHUP_SOURCE_NUMBER.replace("+", "")

    response = requests.post(
        "https://api.gupshup.io/wa/api/v1/msg",
        headers={"apikey": GUPSHUP_API_KEY, "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "channel": "whatsapp",
            "source": clean_from,
            "destination": clean_to,
            "message": _json.dumps({"type": "text", "text": message_text}),
            "src.name": GUPSHUP_APP_NAME,
        },
        timeout=30,
    )

    if response.status_code == 200 and response.json().get("status") == "submitted":
        logger.info(f"Gupshup: message sent to {to_phone}")
        return True

    logger.error(f"Gupshup send failed: {response.status_code} {response.text}")
    return False


def handle_incoming_message(from_phone: str, message_text: str) -> str:
    """
    Process an incoming WhatsApp message: ask the core RAG pipeline,
    send the answer back to the sender, and return the answer text.
    """
    if not message_text or not message_text.strip():
        reply = "Please send a question and I'll do my best to answer from the documents I have."
        send_whatsapp_message(from_phone, reply)
        return reply

    try:
        result = ask(message_text)
        answer = result.get("answer", "Sorry, I couldn't generate an answer.")
    except Exception as e:
        logger.error(f"WhatsApp: error answering message from {from_phone}: {e}", exc_info=True)
        answer = "Sorry, something went wrong answering your question. Please try again."

    send_whatsapp_message(from_phone, answer)

    try:
        call_n8n_workflows(channel="whatsapp", message=message_text, ai_reply=answer)
    except Exception as e:
        logger.warning(f"n8n workflow trigger failed (non-fatal): {e}")

    return answer
