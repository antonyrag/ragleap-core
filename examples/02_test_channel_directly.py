"""
Example: Test a channel adapter's RAG-answering logic directly,
without needing real WhatsApp/Telegram/Discord credentials configured.

Useful for verifying document Q&A works correctly before wiring up
real webhook credentials for any channel.

Usage:
    python examples/02_test_channel_directly.py <channel> <question>
    channel: whatsapp | telegram | discord
"""
import os
import sys

# Add project root to path so 'channels' package is importable when running
# this script directly (e.g. python3 examples/02_test_channel_directly.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_whatsapp(question: str) -> str:
    from channels.whatsapp.router import handle_incoming_message
    return handle_incoming_message("+10000000000", question)


def test_telegram(question: str) -> str:
    from channels.telegram.router import handle_incoming_message
    return handle_incoming_message(999888777, question)


def test_discord(question: str) -> str:
    from channels.discord.router import handle_incoming_message
    return handle_incoming_message("123456789", question)


CHANNEL_FUNCS = {
    "whatsapp": test_whatsapp,
    "telegram": test_telegram,
    "discord": test_discord,
}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in CHANNEL_FUNCS:
        print("Usage: python examples/02_test_channel_directly.py <whatsapp|telegram|discord> <question>")
        sys.exit(1)

    channel, question = sys.argv[1], sys.argv[2]
    print(f"Testing {channel} with question: {question}\n")

    answer = CHANNEL_FUNCS[channel](question)
    print(f"Answer: {answer}")
    print(f"\nNote: if no {channel.upper()}_BOT_TOKEN is set in .env, the actual")
    print("message send will fail and log an error — that's expected. The")
    print("RAG answer above is still real and correct.")
