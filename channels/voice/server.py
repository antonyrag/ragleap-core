"""
Standalone WebSocket server for the RagLeap Core voice channel.

Twilio connects here directly via Media Streams — this is separate from
the main FastAPI app (core/api.py) because Twilio's real-time audio
protocol needs a raw WebSocket server, not an HTTP request/response route.

Run with: python3 -m channels.voice.server
Twilio's <Connect><Stream> TwiML should point to this server's address,
e.g. wss://your-domain.com:8765
"""
import asyncio
import logging
import os

import websockets

from channels.voice.router import handle_call

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VOICE_SERVER_PORT = int(os.environ.get("VOICE_SERVER_PORT", "8765"))


async def main():
    logger.info(f"Voice server starting on port {VOICE_SERVER_PORT}...")
    async with websockets.serve(handle_call, "0.0.0.0", VOICE_SERVER_PORT):
        logger.info(f"Voice server listening on 0.0.0.0:{VOICE_SERVER_PORT}")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
