"""
Embedding for ragleap-rag.
Bring-your-own-key: supports Gemini, OpenAI, Mistral, Together, Ollama
(all OpenAI-compatible), plus Cohere and Voyage AI (own API shapes).
Configure explicitly via EmbeddingConfig, or let it fall back to
environment variables for convenience (useful for scripts/notebooks).

Live-verification status (per this package's own honesty standard):
gemini and openai were verified in earlier sessions. ollama is verified
live in this session (local, no API key, via nomic-embed-text). mistral,
together, and cohere/voyage are code-complete based on public API
documentation but NOT live-verified against a real account - same
caveat already attached to the Pinecone vector backend. Treat their
defaults (models, dimensions) as best-effort until confirmed live.
"""
import os
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

# Providers whose embeddings endpoint is OpenAI-compatible (same request/
# response shape as OpenAI's /v1/embeddings) - reuses the openai package's
# client pointed at a custom base_url, same trick generation.py uses.
OPENAI_COMPATIBLE_BASE_URLS = {
    "openai":   "https://api.openai.com/v1",
    "mistral":  "https://api.mistral.ai/v1",
    "together": "https://api.together.xyz/v1",
    "ollama":   "http://localhost:11434/v1",
}

# Providers with their own (non-OpenAI-compatible) response shape.
CUSTOM_SHAPE_PROVIDERS = ("cohere", "voyage")

_ALL_PROVIDERS = ("gemini",) + tuple(OPENAI_COMPATIBLE_BASE_URLS.keys()) + CUSTOM_SHAPE_PROVIDERS + ("custom",)


@dataclass
class EmbeddingConfig:
    """Explicit embedding provider configuration. Use this for library
    integration rather than relying on environment variables.

    No model or dimensions value is ever hardcoded as a silent default -
    provider model names, availability, and dimensions all change over
    time (a hardcoded gemini generation model default broke in production
    mid-project - see CHANGELOG v0.8.1/v0.9.0), so this always requires
    you to know and specify both, one way or another (constructor arg or
    environment variable)."""
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    dimensions: Optional[int] = None
    base_url: Optional[str] = None

    def __post_init__(self):
        self.provider = self.provider.lower()

        if self.provider == "gemini":
            self.api_key = self.api_key or os.environ.get("GEMINI_API_KEY")
            self.model = self.model or os.environ.get("GEMINI_EMBEDDING_MODEL")
            env_dims = os.environ.get("EMBEDDING_DIMENSIONS")
            self.dimensions = self.dimensions or (int(env_dims) if env_dims else None)
        elif self.provider in OPENAI_COMPATIBLE_BASE_URLS:
            self.api_key = self.api_key or os.environ.get(f"{self.provider.upper()}_API_KEY")
            self.model = self.model or os.environ.get(f"{self.provider.upper()}_EMBEDDING_MODEL")
            env_dims = os.environ.get(f"{self.provider.upper()}_EMBEDDING_DIMENSIONS") or os.environ.get("EMBEDDING_DIMENSIONS")
            self.dimensions = self.dimensions or (int(env_dims) if env_dims else None)
            self.base_url = self.base_url or OPENAI_COMPATIBLE_BASE_URLS[self.provider]
        elif self.provider in CUSTOM_SHAPE_PROVIDERS:
            self.api_key = self.api_key or os.environ.get(f"{self.provider.upper()}_API_KEY")
            self.model = self.model or os.environ.get(f"{self.provider.upper()}_EMBEDDING_MODEL")
            env_dims = os.environ.get(f"{self.provider.upper()}_EMBEDDING_DIMENSIONS") or os.environ.get("EMBEDDING_DIMENSIONS")
            self.dimensions = self.dimensions or (int(env_dims) if env_dims else None)
        elif self.provider == "custom":
            # Any OpenAI-compatible embeddings endpoint not already named
            # above - self-hosted servers (vLLM, LM Studio, etc.), or a
            # provider without dedicated code here yet (many Chinese
            # providers - Qwen/DashScope, Zhipu/GLM, Moonshot/Kimi - ship
            # OpenAI-compatible modes and work via this path today).
            self.api_key = self.api_key or os.environ.get("CUSTOM_EMBEDDING_API_KEY")
            self.model = self.model or os.environ.get("CUSTOM_EMBEDDING_MODEL")
            env_dims = os.environ.get("CUSTOM_EMBEDDING_DIMENSIONS") or os.environ.get("EMBEDDING_DIMENSIONS")
            self.dimensions = self.dimensions or (int(env_dims) if env_dims else None)
            self.base_url = self.base_url or os.environ.get("CUSTOM_EMBEDDING_BASE_URL")
            if not self.base_url:
                raise ValueError(
                    "No base_url for provider 'custom'. Pass base_url= explicitly "
                    "to EmbeddingConfig(), or set CUSTOM_EMBEDDING_BASE_URL in your "
                    "environment - it must point to an OpenAI-compatible /embeddings endpoint."
                )
        else:
            raise ValueError(
                f"Unknown embedding provider '{self.provider}'. Supported: "
                f"{', '.join(_ALL_PROVIDERS)}."
            )

        if not self.api_key and self.provider != "ollama":
            raise ValueError(
                f"No API key for embedding provider '{self.provider}'. Pass api_key= "
                f"explicitly to EmbeddingConfig(), or set {self.provider.upper()}_API_KEY "
                f"in your environment."
            )
        if not self.model:
            raise ValueError(
                f"No embedding model specified for provider '{self.provider}'. Pass "
                f"model= explicitly to EmbeddingConfig(), or set "
                f"{self.provider.upper()}_EMBEDDING_MODEL in your environment. "
                f"ragleap-rag never hardcodes a default embedding model - provider "
                f"model availability and dimensions change too frequently for a "
                f"baked-in default to stay reliable."
            )
        if not self.dimensions:
            raise ValueError(
                f"No dimensions specified for embedding provider '{self.provider}' "
                f"model '{self.model}'. Pass dimensions= explicitly to "
                f"EmbeddingConfig(), or set EMBEDDING_DIMENSIONS (or "
                f"{self.provider.upper()}_EMBEDDING_DIMENSIONS) in your environment - "
                f"dimensions must match your chosen model exactly, and ragleap-rag "
                f"can't safely guess it."
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
            elif self.config.provider in OPENAI_COMPATIBLE_BASE_URLS or self.config.provider == "custom":
                return self._embed_openai_compatible(text)
            elif self.config.provider == "cohere":
                return self._embed_cohere([text])[0]
            elif self.config.provider == "voyage":
                return self._embed_voyage([text])[0]
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
            elif self.config.provider in OPENAI_COMPATIBLE_BASE_URLS or self.config.provider == "custom":
                return self._embed_batch_openai_compatible(texts)
            elif self.config.provider == "cohere":
                return self._embed_cohere(texts)
            elif self.config.provider == "voyage":
                return self._embed_voyage(texts)
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

    def _embed_openai_compatible(self, text: str) -> Optional[List[float]]:
        """Shared path for openai/mistral/together/ollama - all expose the
        same /embeddings request+response shape. dimensions= is only sent
        when explicitly set, since not every OpenAI-compatible provider's
        embeddings endpoint accepts that param (Ollama's does not)."""
        import openai
        client = openai.OpenAI(api_key=self.config.api_key or "not-needed", base_url=self.config.base_url)
        kwargs = {"model": self.config.model, "input": text}
        if self.config.provider == "openai" and self.config.dimensions:
            kwargs["dimensions"] = self.config.dimensions
        response = client.embeddings.create(**kwargs)
        return response.data[0].embedding

    def _embed_batch_openai_compatible(self, texts: List[str]) -> List[Optional[List[float]]]:
        import openai
        client = openai.OpenAI(api_key=self.config.api_key or "not-needed", base_url=self.config.base_url)
        kwargs = {"model": self.config.model, "input": texts}
        if self.config.provider == "openai" and self.config.dimensions:
            kwargs["dimensions"] = self.config.dimensions
        response = client.embeddings.create(**kwargs)
        return [d.embedding for d in response.data]

    def _embed_cohere(self, texts: List[str]) -> List[Optional[List[float]]]:
        """NOT live-verified - implemented per Cohere's public API docs.
        Always uses input_type='search_document' since embed_text()/
        embed_batch() don't currently distinguish query vs. document
        embedding calls - a known limitation, not an optimal setup."""
        import requests
        response = requests.post(
            "https://api.cohere.ai/v1/embed",
            headers={"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"},
            json={"texts": texts, "model": self.config.model, "input_type": "search_document"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["embeddings"]

    def _embed_voyage(self, texts: List[str]) -> List[Optional[List[float]]]:
        """NOT live-verified - implemented per Voyage AI's public API docs."""
        import requests
        response = requests.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"},
            json={"input": texts, "model": self.config.model},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()["data"]
        return [d["embedding"] for d in data]
