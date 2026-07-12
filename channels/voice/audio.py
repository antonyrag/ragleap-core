"""
Speech-to-text and text-to-speech for the RagLeap Core voice channel.
v1 supports OpenAI Whisper (STT) and OpenAI TTS only — Deepgram and
ElevenLabs are documented as good-first-issue additions, not yet implemented.
"""
import io
import logging

import requests

logger = logging.getLogger(__name__)

OPENAI_STT_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"


def transcribe_audio(pcm_audio: bytes, api_key: str, sample_rate: int = 8000) -> str:
    """
    Transcribe raw PCM audio using OpenAI Whisper.
    Twilio Media Streams sends mu-law 8kHz audio — caller is responsible
    for converting to a WAV/PCM format Whisper accepts before calling this.
    """
    if not api_key:
        logger.error("No OpenAI API key configured for STT — set OPENAI_API_KEY in .env")
        return ""

    files = {"file": ("audio.wav", io.BytesIO(pcm_audio), "audio/wav")}
    data = {"model": "whisper-1"}
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.post(OPENAI_STT_URL, headers=headers, files=files, data=data, timeout=15)
        response.raise_for_status()
        return response.json().get("text", "").strip()
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return ""


def text_to_speech(text: str, api_key: str, voice: str = "nova") -> bytes:
    """Generate speech audio from text using OpenAI TTS. Returns raw audio bytes (mp3)."""
    if not api_key:
        logger.error("No OpenAI API key configured for TTS — set OPENAI_API_KEY in .env")
        return b""

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": "tts-1", "input": text, "voice": voice, "response_format": "mp3"}

    try:
        response = requests.post(OPENAI_TTS_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"OpenAI TTS failed: {e}")
        return b""
