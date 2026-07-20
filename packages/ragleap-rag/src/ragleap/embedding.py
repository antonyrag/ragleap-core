"""
Embedding for ragleap-rag.
Bring-your-own-key: supports Gemini and OpenAI embedding providers.
Configure explicitly via EmbeddingConfig, or let it fall back to
environment variables for convenience (useful for scripts/notebooks).
"""
import os
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "gemini": "models/gemini-embedding-001",
    "openai": "text-embedding-3-small",
}
DEFAULT_DIMENSIONS = {
    "gemini": 3072,
    "openai": 1536,
}


@dataclass
class EmbeddingConfig:
    """Explicit embedding provider configuration. Use this for library
    integration rather than relying on environment variables."""
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    dimensions: Optional[int] = None

    def __post_init__(self):
        self.provider = self.provider.lower()

        if self.provider == "gemini":
            self.api_key = self.api_key or os.environ.get("GEMINI_API_KEY")
            self.model = self.model or os.environ.get("GEMINI_EMBEDDING_MODEL", DEFAULT_MODELS["gemini"])
            self.dimensions = self.dimensions or int(
                os.environ.get("EMBEDDING_DIMENSIONS", str(DEFAULT_DIMENSIONS["gemini"]))
            )
        elif self.provider == "openai":
            self.api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
            self.model = self.model or os.environ.get("OPENAI_EMBEDDING_MODEL", DEFAULT_MODELS["openai"])
            self.dimensions = self.dimensions or int(
                os.environ.get("EMBEDDING_DIMENSIONS", str(DEFAULT_DIMENSIONS["openai"]))
            )
        else:
            raise ValueError(
                f"Unknown embedding provider '{self.provider}'. Supported: gemini, openai."
            )

        if not self.api_key:
            raise ValueError(
                f"No API key for embedding provider '{self.provider}'. Pass api_key= "
                f"explicitly to EmbeddingConfig(), or set "
                f"{'GEMINI_API_KEY' if self.provider == 'gemini' else 'OPENAI_API_KEY'} "
                f"in your environment."
            )


class EmbeddingService:
    """Generates vector embeddings using the configured provider."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config
        # Convenience passthrough attrs (some callers may read these directly)
        self.model = config.model
        self.dimensions = config.dimensions

    def embed_text(self, text: str) -> Optional[List[float]]:
        """Generate an embedding vector for a single piece of text."""
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            return None

        try:
            if self.config.provider == "gemini":
                return self._embed_gemini(text)
            elif self.config.provider == "openai":
                return self._embed_openai(text)
        except Exception as e:
            logger.error(f"Embedding generation failed ({self.config.provider}): {e}")
            return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        try:
            if self.config.provider == "gemini":
                return self._embed_batch_gemini(texts)
            elif self.config.provider == "openai":
                return self._embed_batch_openai(texts)
        except Exception as e:
            logger.error(f"Batch embedding generation failed ({self.config.provider}): {e}")
            return [None] * len(texts)

    def _embed_gemini(self, text: str) -> Optional[List[float]]:
        import google.genai as genai
        client = genai.Client(api_key=self.config.api_key)
        response = client.models.embed_content(model=self.config.model, contents=text)
        return response.embeddings[0].values

    def _embed_batch_gemini(self, texts: List[str]) -> List[Optional[List[float]]]:
        import google.genai as genai
        client = genai.Client(api_key=self.config.api_key)
        response = client.models.embed_content(model=self.config.model, contents=texts)
        return [e.values for e in response.embeddings]

    def _embed_openai(self, text: str) -> Optional[List[float]]:
        import openai
        client = openai.OpenAI(api_key=self.config.api_key)
        response = client.embeddings.create(
            model=self.config.model, input=text, dimensions=self.config.dimensions
        )
        return response.data[0].embedding

    def _embed_batch_openai(self, texts: List[str]) -> List[Optional[List[float]]]:
        import openai
        client = openai.OpenAI(api_key=self.config.api_key)
        response = client.embeddings.create(
            model=self.config.model, input=texts, dimensions=self.config.dimensions
        )
        return [d.embedding for d in response.data]
