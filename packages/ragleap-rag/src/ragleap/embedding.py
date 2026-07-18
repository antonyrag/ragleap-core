"""
Embedding for ragleap-rag.
Uses Google Gemini embeddings (gemini-embedding-001, 3072 dimensions).
Bring-your-own-key: pass api_key explicitly, or set GEMINI_API_KEY in
the environment as a convenience fallback (useful for scripts/notebooks,
but explicit is preferred for library usage inside a larger app).
"""
import os
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "models/gemini-embedding-001"
DEFAULT_DIMENSIONS = 3072


class EmbeddingService:
    """Generates vector embeddings using Google Gemini."""

    def __init__(self, api_key: Optional[str] = None, model: str = None, dimensions: int = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model or os.environ.get("GEMINI_EMBEDDING_MODEL", DEFAULT_MODEL)
        self.dimensions = dimensions or int(os.environ.get("EMBEDDING_DIMENSIONS", str(DEFAULT_DIMENSIONS)))

        if not self.api_key:
            raise ValueError(
                "No Gemini API key provided. Pass api_key= to EmbeddingService(), "
                "or set GEMINI_API_KEY in your environment. Get a free key at "
                "https://aistudio.google.com/apikey — there is no system-provided key."
            )

    def embed_text(self, text: str) -> Optional[List[float]]:
        """Generate an embedding vector for a single piece of text."""
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            return None

        try:
            import google.genai as genai
            client = genai.Client(api_key=self.api_key)
            response = client.models.embed_content(model=self.model, contents=text)
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
            response = client.models.embed_content(model=self.model, contents=texts)
            return [e.values for e in response.embeddings]
        except Exception as e:
            logger.error(f"Batch embedding generation failed: {e}")
            return [None] * len(texts)
