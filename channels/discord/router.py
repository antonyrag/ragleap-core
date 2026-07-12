"""
Discord channel adapter for RagLeap Core.

Receives Discord messages via webhook, answers them using the core RAG
pipeline (core.chat.ask), and sends the response back. Single-tenant:
one bot, one document set, configured entirely via .env.
"""
import os
import logging

import requests

from core.chat import ask

logger = logging.getLogger(__name__)

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY")

DISCORD_API_URL = "https://discord.com/api/v10"
MAX_DISCORD_MESSAGE_LENGTH = 2000


def verify_discord_signature(signature: str, timestamp: str, body: bytes) -> bool:
    """Verify a Discord interaction request using Ed25519, per Discord's official algorithm."""
    if not signature or not timestamp or not DISCORD_PUBLIC_KEY:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(DISCORD_PUBLIC_KEY))
        message = timestamp.encode("utf-8") + body
        public_key.verify(bytes.fromhex(signature), message)
        return True
    except Exception as e:
        logger.warning(f"Discord signature verification failed: {e}")
        return False


def send_discord_message(channel_id, message_text: str) -> bool:
    """Send a message to a Discord channel via the Bot API."""
    if not DISCORD_BOT_TOKEN:
        logger.error("Discord bot not configured — set DISCORD_BOT_TOKEN in .env")
        return False

    if len(message_text) > MAX_DISCORD_MESSAGE_LENGTH:
        message_text = message_text[:MAX_DISCORD_MESSAGE_LENGTH - 20] + "...\n(truncated)"

    url = f"{DISCORD_API_URL}/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json={"content": message_text}, timeout=30)

    if response.status_code in (200, 201):
        logger.info(f"Discord: message sent to channel {channel_id}")
        return True

    logger.error(f"Discord send failed: {response.status_code} {response.text}")
    return False


def handle_incoming_message(channel_id, message_text: str) -> str:
    """
    Process an incoming Discord message: ask the core RAG pipeline,
    send the answer back to the channel, and return the answer text.
    """
    if not message_text or not message_text.strip():
        reply = "Please send a question and I'll do my best to answer from the documents I have."
        send_discord_message(channel_id, reply)
        return reply

    try:
        result = ask(message_text)
        answer = result.get("answer", "Sorry, I couldn't generate an answer.")
    except Exception as e:
        logger.error(f"Discord: error answering message from channel {channel_id}: {e}", exc_info=True)
        answer = "Sorry, something went wrong answering your question. Please try again."

    send_discord_message(channel_id, answer)
    return answer
