"""
Telegram channel adapter for RagLeap Core.

Receives Telegram messages via webhook, answers them using the core RAG
pipeline (core.chat.ask), and sends the response back. Single-tenant:
one bot, one document set, configured entirely via .env.
"""
import os
import hmac
import hashlib
import logging

import requests

from core.chat import ask
from core.workflows import call_n8n_workflows

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"
MAX_TELEGRAM_MESSAGE_LENGTH = 4096


def _verify_webhook_secret(received_secret: str) -> bool:
    """Verify the X-Telegram-Bot-Api-Secret-Token header against our configured secret."""
    if not TELEGRAM_WEBHOOK_SECRET:
        # No secret configured — skip verification (not recommended for production,
        # but allows quick local testing).
        logger.warning("TELEGRAM_WEBHOOK_SECRET not set — webhook signature not verified")
        return True
    if not received_secret:
        return False
    return hmac.compare_digest(received_secret, TELEGRAM_WEBHOOK_SECRET)


def send_telegram_message(chat_id, message_text: str) -> bool:
    """Send a message to a Telegram chat via the Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot not configured — set TELEGRAM_BOT_TOKEN in .env")
        return False

    if len(message_text) > MAX_TELEGRAM_MESSAGE_LENGTH:
        message_text = message_text[:MAX_TELEGRAM_MESSAGE_LENGTH - 20] + "...\n(truncated)"

    url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN, method="sendMessage")
    response = requests.post(url, json={"chat_id": chat_id, "text": message_text}, timeout=30)

    if response.status_code == 200 and response.json().get("ok"):
        logger.info(f"Telegram: message sent to chat {chat_id}")
        return True

    logger.error(f"Telegram send failed: {response.status_code} {response.text}")
    return False


def send_typing_action(chat_id) -> None:
    """Show 'typing...' in the chat while the bot is processing."""
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN, method="sendChatAction")
        requests.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except Exception:
        pass  # typing indicator is optional, never fail the request over it


def handle_incoming_message(chat_id, message_text: str) -> str:
    """
    Process an incoming Telegram message: ask the core RAG pipeline,
    send the answer back to the chat, and return the answer text.
    """
    if not message_text or not message_text.strip():
        reply = "Please send a question and I'll do my best to answer from the documents I have."
        send_telegram_message(chat_id, reply)
        return reply

    if message_text.strip() == "/start":
        welcome = (
            "Hi! I'm a document Q&A bot powered by RagLeap Core. "
            "Send me a question and I'll search through the documents I have to answer it."
        )
        send_telegram_message(chat_id, welcome)
        return welcome

    send_typing_action(chat_id)

    try:
        result = ask(message_text)
        answer = result.get("answer", "Sorry, I couldn't generate an answer.")
    except Exception as e:
        logger.error(f"Telegram: error answering message from chat {chat_id}: {e}", exc_info=True)
        answer = "Sorry, something went wrong answering your question. Please try again."

    send_telegram_message(chat_id, answer)

    try:
        call_n8n_workflows(channel="telegram", message=message_text, ai_reply=answer)
    except Exception as e:
        logger.warning(f"n8n workflow trigger failed (non-fatal): {e}")

    return answer
