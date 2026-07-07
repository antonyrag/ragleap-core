"""
Answer Generation Service for RagLeap Core
Bring-your-own-key only — no system key, no fallback.

Supports multiple LLM providers via LLM_PROVIDER env var (default: gemini).
Native SDK providers: gemini, anthropic
OpenAI-compatible providers (via openai SDK + custom base_url): everyone else.
"""
import os
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()
GEMINI_CHAT_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.5-flash")

# Base URLs for OpenAI-compatible providers. gemini and anthropic use their
# own native SDKs and don't need a base_url override here.
PROVIDER_BASE_URLS = {
    "openai":     "https://api.openai.com/v1",
    "mistral":    "https://api.mistral.ai/v1",
    "groq":       "https://api.groq.com/openai/v1",
    "together":   "https://api.together.xyz/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama":     "http://localhost:11434/v1",
    "deepseek":   "https://api.deepseek.com/v1",
    "xai":        "https://api.x.ai/v1",
    "cohere":     "https://api.cohere.ai/v1",
    "perplexity": "https://api.perplexity.ai",
    "qwen":       "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "moonshot":   "https://api.moonshot.cn/v1",
    "zhipu":      "https://open.bigmodel.cn/api/paas/v4",
    "yi":         "https://api.01.ai/v1",
    "baidu":      "https://qianfan.baidubce.com/v2",
    "minimax":    "https://api.minimax.chat/v1",
    "custom":     None,  # requires CUSTOM_BASE_URL env var
}

SYSTEM_PROMPT = """You are a helpful assistant that answers questions using ONLY the provided context.
If the answer is not in the context, say clearly that you don't have that information — do not make things up.
Always be concise and cite which document your answer came from when possible."""


class GenerationService:
    """
    Generates a grounded answer using the configured LLM_PROVIDER,
    given a query and retrieved chunks.
    """

    def __init__(self):
        self.provider = LLM_PROVIDER

        if self.provider == "gemini":
            self.api_key = os.environ.get("GEMINI_API_KEY")
            self.model = GEMINI_CHAT_MODEL
            if not self.api_key:
                raise ValueError(
                    "GEMINI_API_KEY is not set. Get one at "
                    "https://aistudio.google.com/apikey and add it to .env."
                )

        elif self.provider == "anthropic":
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")
            self.model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
            if not self.api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY is not set. Get one at "
                    "https://console.anthropic.com and add it to .env."
                )

        elif self.provider in PROVIDER_BASE_URLS:
            key_env = f"{self.provider.upper()}_API_KEY"
            self.api_key = os.environ.get(key_env)
            self.model = os.environ.get(f"{self.provider.upper()}_MODEL", "")
            self.base_url = os.environ.get("CUSTOM_BASE_URL") if self.provider == "custom" else PROVIDER_BASE_URLS[self.provider]

            if not self.api_key and self.provider != "ollama":
                raise ValueError(
                    f"{key_env} is not set. Add your {self.provider} API key to .env."
                )
            if not self.base_url:
                raise ValueError(
                    f"No base URL configured for provider '{self.provider}'. "
                    f"Set CUSTOM_BASE_URL in .env if using 'custom'."
                )
            if not self.model:
                raise ValueError(
                    f"{self.provider.upper()}_MODEL is not set in .env."
                )

        else:
            raise ValueError(
                f"Unknown LLM_PROVIDER '{self.provider}'. Supported: gemini, anthropic, "
                f"{', '.join(PROVIDER_BASE_URLS.keys())}."
            )

    def _build_context(self, chunks: List[Dict]) -> str:
        """Format retrieved chunks into a context block with source labels."""
        if not chunks:
            return "No relevant context was found."
        parts = []
        for i, chunk in enumerate(chunks, start=1):
            doc_name = chunk.get("document_name", "unknown document")
            text = chunk.get("text", "")
            parts.append(f"[Source {i}: {doc_name}]\n{text}")
        return "\n\n".join(parts)

    def generate_answer(self, query: str, chunks: List[Dict]) -> Dict:
        """
        Generate an answer to `query` grounded in the given `chunks`.
        Returns a dict: {"answer": str, "sources": List[str]}
        """
        context = self._build_context(chunks)
        sources = list({c.get("document_name", "unknown") for c in chunks})
        prompt = f"""{SYSTEM_PROMPT}

Context:
{context}

Question: {query}
Answer:"""

        try:
            if self.provider == "gemini":
                answer_text = self._call_gemini(prompt)
            elif self.provider == "anthropic":
                answer_text = self._call_anthropic(prompt)
            else:
                answer_text = self._call_openai_compatible(prompt)

            return {"answer": answer_text, "sources": sources}

        except Exception as e:
            logger.error(f"Answer generation failed ({self.provider}): {e}")
            return {
                "answer": f"Sorry, I couldn't generate an answer due to an error: {e}",
                "sources": [],
            }

    def _call_gemini(self, prompt: str) -> str:
        import google.genai as genai
        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(model=self.model, contents=prompt)
        return response.text.strip() if response.text else "No answer generated."

    def _call_anthropic(self, prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip() if response.content else "No answer generated."

    def _call_openai_compatible(self, prompt: str) -> str:
        import openai
        client = openai.OpenAI(api_key=self.api_key or "not-needed", base_url=self.base_url)
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip() if response.choices else "No answer generated."
