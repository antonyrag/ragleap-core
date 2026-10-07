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

EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "64"))
EMBEDDING_TIMEOUT = float(os.environ.get("EMBEDDING_TIMEOUT", "60"))

# provider -> (default base url, default model, default dimensions)
OPENAI_COMPATIBLE = {
    "ollama":     ("http://localhost:11434/v1", "nomic-embed-text", 768),
    "openai":     ("https://api.openai.com/v1", "text-embedding-3-small", 1536),
    "mistral":    ("https://api.mistral.ai/v1", "mistral-embed", 1024),
    "together":   ("https://api.together.xyz/v1", "", 0),
    "openrouter": ("https://openrouter.ai/api/v1", "", 0),
    "qwen":       ("https://dashscope.aliyuncs.com/compatible-mode/v1", "", 0),
    "zhipu":      ("https://open.bigmodel.cn/api/paas/v4", "", 0),
    "custom":     ("", "", 0),
}


def provider() -> str:
    return os.environ.get("EMBEDDING_PROVIDER", "gemini").strip().lower() or "gemini"


def configured_dimensions() -> int:
    raw = os.environ.get("EMBEDDING_DIMENSIONS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return OPENAI_COMPATIBLE.get(provider(), ("", "", 0))[2] or 3072


def _compat_settings(p: str):
    base_default, model_default, _dims = OPENAI_COMPATIBLE[p]
    up = p.upper()
    base_var = "CUSTOM_BASE_URL" if p == "custom" else up + "_BASE_URL"
    base = os.environ.get(base_var, "").strip() or base_default
    model = os.environ.get(up + "_EMBEDDING_MODEL", "").strip() or model_default
    key = os.environ.get(up + "_API_KEY", "").strip()
    return base.rstrip("/"), model, key


def _is_transient(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    return code in EMBEDDING_RETRY_CODES


class EmbeddingService:
    """
    Generates vector embeddings using Google Gemini.
    Requires the user's own GEMINI_API_KEY — no system key, no fallback.
    """

    def __init__(self):
        self.provider = provider()
        self.dimensions = configured_dimensions()
        self.base_url = ""
        if self.provider == "gemini":
            self.model = GEMINI_EMBEDDING_MODEL
            self.api_key = os.environ.get("GEMINI_API_KEY")
        elif self.provider in OPENAI_COMPATIBLE:
            up = self.provider.upper()
            self.base_url, self.model, self.api_key = _compat_settings(self.provider)
            if not self.base_url:
                raise ValueError("Set " + ("CUSTOM" if self.provider == "custom" else up) + "_BASE_URL for EMBEDDING_PROVIDER=" + self.provider + ".")
            if not self.model:
                raise ValueError("Set " + up + "_EMBEDDING_MODEL for EMBEDDING_PROVIDER=" + self.provider + ".")
            if self.provider != "ollama" and not self.api_key:
                raise ValueError("Set " + up + "_API_KEY for EMBEDDING_PROVIDER=" + self.provider + ".")
            if OPENAI_COMPATIBLE[self.provider][2] == 0 and not os.environ.get("EMBEDDING_DIMENSIONS", "").strip().isdigit():
                raise ValueError("Set EMBEDDING_DIMENSIONS to the output size of your " + self.provider + " embedding model.")
        else:
            raise ValueError("Unknown EMBEDDING_PROVIDER '" + self.provider + "'. Use gemini or one of: " + ", ".join(sorted(OPENAI_COMPATIBLE)) + ".")

        if self.provider == "gemini" and not self.api_key:
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
        if self.provider == "gemini":
            return self._embed_text_gemini(text)
        return self._embed_compat([text])[0]

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []
        if self.provider == "gemini":
            return self._embed_batch_gemini(texts)
        return self._embed_compat(texts)

    def _embed_text_gemini(self, text: str) -> Optional[List[float]]:
        """Generate an embedding vector for a single piece of text (Gemini)."""
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

    def _embed_batch_gemini(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts (Gemini)."""
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

    def _embed_compat(self, texts):
        import requests
        url = self.base_url + "/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        out = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[i:i + EMBEDDING_BATCH_SIZE]
            vectors = None
            for attempt in range(EMBEDDING_MAX_RETRIES + 1):
                try:
                    resp = requests.post(url, json={"model": self.model, "input": batch},
                                         headers=headers, timeout=EMBEDDING_TIMEOUT)
                    if resp.status_code in EMBEDDING_RETRY_CODES and attempt < EMBEDDING_MAX_RETRIES:
                        time.sleep(EMBEDDING_RETRY_BASE_DELAY * (2 ** attempt))
                        continue
                    resp.raise_for_status()
                    data = sorted(resp.json()["data"], key=lambda d: d.get("index", 0))
                    vectors = [d["embedding"] for d in data]
                    break
                except Exception as e:
                    logger.error("Embedding request failed: %s", type(e).__name__)
                    break
            ok = (vectors is not None and len(vectors) == len(batch)
                  and all(len(v) == self.dimensions for v in vectors))
            if vectors is not None and not ok:
                logger.error("Embedding size mismatch: expected %s dims (EMBEDDING_DIMENSIONS)", self.dimensions)
            out.extend(vectors if ok else [None] * len(batch))
        return out
