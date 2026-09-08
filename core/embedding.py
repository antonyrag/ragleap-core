"""
Embedding Service for RagLeap Core
Uses Google Gemini embeddings (gemini-embedding-001, 3072 dimensions) —
the same embedding technology used in RagLeap's production platform.

Bring-your-own-key only: this service NEVER falls back to a shared or
system-provided key. You must supply your own GEMINI_API_KEY.
"""
import os
import time
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

GEMINI_EMBEDDING_MODEL = os.environ.get("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "3072"))

# Deliberately NOT a cross-provider fallback: every stored chunk is embedded
# with this exact model at EMBEDDING_DIMENSIONS, so a different provider's
# embedding would land in a different, incompatible vector space and
# corrupt similarity search silently rather than failing loudly. This is a
# same-provider retry for genuinely transient errors only (429 rate limit,
# 503 server overload) - anything else (bad key, malformed request) fails
# fast on the first try, as before.
EMBEDDING_RETRY_CODES = {429, 503}
EMBEDDING_MAX_RETRIES = int(os.environ.get("EMBEDDING_MAX_RETRIES", "3"))
EMBEDDING_RETRY_BASE_DELAY = float(os.environ.get("EMBEDDING_RETRY_BASE_DELAY", "1.0"))


def _is_transient(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    return code in EMBEDDING_RETRY_CODES


class EmbeddingService:
    """
    Generates vector embeddings using Google Gemini.
    Requires the user's own GEMINI_API_KEY — no system key, no fallback.
    """

    def __init__(self):
        self.model = GEMINI_EMBEDDING_MODEL
        self.dimensions = EMBEDDING_DIMENSIONS
        self.api_key = os.environ.get("GEMINI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. RagLeap Core requires your own "
                "Gemini API key — get one at https://aistudio.google.com/apikey "
                "and add it to your .env file. There is no system-provided key."
            )

    def embed_text(self, text: str) -> Optional[List[float]]:
        """Generate an embedding vector for a single piece of text."""
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            return None

        try:
            import google.genai as genai
            client = genai.Client(api_key=self.api_key)
            for attempt in range(EMBEDDING_MAX_RETRIES + 1):
                try:
                    response = client.models.embed_content(
                        model=self.model,
                        contents=text,
                    )
                    return response.embeddings[0].values
                except Exception as e:
                    if _is_transient(e) and attempt < EMBEDDING_MAX_RETRIES:
                        delay = EMBEDDING_RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            f"Embedding request hit a transient error "
                            f"(code={getattr(e, 'code', '?')}), retrying in "
                            f"{delay:.1f}s (attempt {attempt + 1}/{EMBEDDING_MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        continue
                    raise
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        try:
            import google.genai as genai
            client = genai.Client(api_key=self.api_key)
            for attempt in range(EMBEDDING_MAX_RETRIES + 1):
                try:
                    response = client.models.embed_content(
                        model=self.model,
                        contents=texts,
                    )
                    return [e.values for e in response.embeddings]
                except Exception as e:
                    if _is_transient(e) and attempt < EMBEDDING_MAX_RETRIES:
                        delay = EMBEDDING_RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            f"Batch embedding request hit a transient error "
                            f"(code={getattr(e, 'code', '?')}), retrying in "
                            f"{delay:.1f}s (attempt {attempt + 1}/{EMBEDDING_MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        continue
                    raise
        except Exception as e:
            logger.error(f"Batch embedding generation failed: {e}")
            return [None] * len(texts)
