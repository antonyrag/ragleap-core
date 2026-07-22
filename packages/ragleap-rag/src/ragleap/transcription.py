"""
Audio transcription for ragleap-rag. Pluggable providers - OpenAI's
hosted Whisper API by default, or Deepgram - rather than a hardcoded
single choice. Whisper is a strong general-purpose baseline but has
real, documented weak spots: accuracy varies significantly by
language (strongest on English/major European languages), it has no
built-in denoising (quiet/noisy audio genuinely degrades
transcription quality - Whisper does not compensate for this), and no
domain-vocabulary biasing by default (brand names, jargon, and
proper nouns commonly get mangled unless a prompt hint is supplied).
Deepgram is offered as an alternative for cases where these
limitations matter.

Both providers here use hosted APIs (no local model weights, no
torch/CUDA dependency) - a deliberate choice given ragleap-rag's
existing experience with the CUDA-bloat problem in the reranking
feature. Local/offline Whisper (via the openai-whisper package) is
not currently supported - it would need its own provider option and
pulls in torch, similar tradeoffs to the reranking dependency.
"""
import io
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionConfig:
    """Explicit transcription provider configuration."""
    provider: str = "whisper"
    api_key: Optional[str] = None
    model: Optional[str] = None
    language: Optional[str] = None  # ISO 639-1 code, e.g. "en" - omit for auto-detect
    prompt: Optional[str] = None  # optional vocabulary/context hint (Whisper only)

    def __post_init__(self):
        import os
        self.provider = self.provider.lower()

        if self.provider == "whisper":
            self.api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
            self.model = self.model or "whisper-1"
        elif self.provider == "deepgram":
            self.api_key = self.api_key or os.environ.get("DEEPGRAM_API_KEY")
            self.model = self.model or "nova-2"
        else:
            raise ValueError(f"Unknown transcription provider '{self.provider}'. Supported: whisper, deepgram.")

        if not self.api_key:
            raise ValueError(
                f"No API key for transcription provider '{self.provider}'. Pass api_key= explicitly, "
                f"or set {'OPENAI_API_KEY' if self.provider == 'whisper' else 'DEEPGRAM_API_KEY'} in your environment."
            )


class TranscriptionService:
    """Transcribes audio to text using the configured provider."""

    def __init__(self, config: TranscriptionConfig):
        self.config = config

    def transcribe(self, filename: str, audio_bytes: bytes) -> str:
        if self.config.provider == "whisper":
            return self._transcribe_whisper(filename, audio_bytes)
        elif self.config.provider == "deepgram":
            return self._transcribe_deepgram(audio_bytes)

    def _transcribe_whisper(self, filename: str, audio_bytes: bytes) -> str:
        try:
            import openai
        except ImportError as e:
            raise ValueError("openai package is required for Whisper transcription — pip install ragleap-rag[openai]") from e

        client = openai.OpenAI(api_key=self.config.api_key)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename  # OpenAI's client needs a filename for format detection

        kwargs = {"model": self.config.model, "file": audio_file}
        if self.config.language:
            kwargs["language"] = self.config.language
        if self.config.prompt:
            kwargs["prompt"] = self.config.prompt

        response = client.audio.transcriptions.create(**kwargs)
        text = response.text if hasattr(response, "text") else str(response)
        if not text or not text.strip():
            raise ValueError("Whisper returned an empty transcription — check the audio has audible speech.")
        return text

    def _transcribe_deepgram(self, audio_bytes: bytes) -> str:
        try:
            import requests
        except ImportError as e:
            raise ValueError("requests package is required for Deepgram transcription") from e

        params = {"model": self.config.model, "smart_format": "true"}
        if self.config.language:
            params["language"] = self.config.language

        response = requests.post(
            "https://api.deepgram.com/v1/listen",
            headers={"Authorization": f"Token {self.config.api_key}", "Content-Type": "audio/*"},
            params=params,
            data=audio_bytes,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

        try:
            text = data["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError) as e:
            raise ValueError(f"Unexpected Deepgram response shape: {data}") from e

        if not text or not text.strip():
            raise ValueError("Deepgram returned an empty transcription — check the audio has audible speech.")
        return text
