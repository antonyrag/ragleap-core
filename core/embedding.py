"""
Embedding Service for RagLeap Core
Uses Google Gemini embeddings (gemini-embedding-001, 3072 dimensions) —
the same embedding technology used in RagLeap's production platform.

Bring-your-own-key only: this service NEVER falls back to a shared or
system-provided key. You must supply your own GEMINI_API_KEY.
"""
import os
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

GEMINI_EMBEDDING_MODEL = os.environ.get("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "3072"))


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
            response = client.models.embed_content(
                model=self.model,
                contents=text,
            )
            return response.embeddings[0].values
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
            response = client.models.embed_content(
                model=self.model,
                contents=texts,
            )
            return [e.values for e in response.embeddings]
        except Exception as e:
            logger.error(f"Batch embedding generation failed: {e}")
            return [None] * len(texts)
