"""
Answer Generation Service for RagLeap Core
Bring-your-own-key only — no system key, no fallback provided by RagLeap
itself. You can configure your OWN fallback chain across providers you
have keys for (see LLM_FALLBACK_PROVIDERS below).

Supports multiple LLM providers via LLM_PROVIDER env var (default: gemini).
Native SDK providers: gemini, anthropic
OpenAI-compatible providers (via openai SDK + custom base_url): everyone else.
"""
import os
import logging
from typing import List, Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()
GEMINI_CHAT_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.5-flash")

DEFAULT_TEMPERATURE = float(os.environ.get("DEFAULT_TEMPERATURE", "0.3"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "1024"))

LLM_FALLBACK_PROVIDERS = [
    p.strip().lower() for p in os.environ.get("LLM_FALLBACK_PROVIDERS", "").split(",") if p.strip()
]

# Rough context-size budget for retrieved chunks, in characters (not exact
# tokens — a real per-provider tokenizer call would add latency and cost
# per request just to measure cost, which is counterproductive). ~4 chars
# per token is a widely-used English-text approximation. When the combined
# retrieved context exceeds this, lowest-ranked chunks are dropped first.
# Set to 0 to disable trimming entirely.
MAX_CONTEXT_CHARS = int(os.environ.get("MAX_CONTEXT_CHARS", "12000"))

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


def _resolve_provider_config(provider: str, required: bool = True) -> Optional[Dict]:
    """
    Resolve a provider name into {provider, api_key, model, base_url}.
    required=True (primary provider) raises ValueError on missing config.
    required=False (fallback providers) returns None and logs a warning.
    """
    provider = provider.lower()

    def _fail(msg: str) -> Optional[Dict]:
        if required:
            raise ValueError(msg)
        logger.warning(f"Skipping fallback provider '{provider}': {msg}")
        return None

    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return _fail(
                "GEMINI_API_KEY is not set. Get one at "
                "https://aistudio.google.com/apikey and add it to .env."
            )
        return {"provider": "gemini", "api_key": api_key, "model": GEMINI_CHAT_MODEL, "base_url": None}

    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return _fail(
                "ANTHROPIC_API_KEY is not set. Get one at "
                "https://console.anthropic.com and add it to .env."
            )
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        return {"provider": "anthropic", "api_key": api_key, "model": model, "base_url": None}

    elif provider in PROVIDER_BASE_URLS:
        key_env = f"{provider.upper()}_API_KEY"
        api_key = os.environ.get(key_env)
        model = os.environ.get(f"{provider.upper()}_MODEL", "")
        base_url = os.environ.get("CUSTOM_BASE_URL") if provider == "custom" else PROVIDER_BASE_URLS[provider]

        if not api_key and provider != "ollama":
            return _fail(f"{key_env} is not set. Add your {provider} API key to .env.")
        if not base_url:
            return _fail(
                f"No base URL configured for provider '{provider}'. "
                f"Set CUSTOM_BASE_URL in .env if using 'custom'."
            )
        if not model:
            return _fail(f"{provider.upper()}_MODEL is not set in .env.")

        return {"provider": provider, "api_key": api_key, "model": model, "base_url": base_url}

    else:
        return _fail(
            f"Unknown provider '{provider}'. Supported: gemini, anthropic, "
            f"{', '.join(PROVIDER_BASE_URLS.keys())}."
        )


class GenerationService:
    """
    Generates a grounded answer using the configured LLM_PROVIDER,
    given a query and retrieved chunks. Supports per-call temperature/
    system_prompt/max_tokens overrides, streaming, a fallback chain
    across providers, context-size trimming, and real token usage
    reporting (for blocking calls).
    """

    def __init__(self):
        self.primary_config = _resolve_provider_config(LLM_PROVIDER, required=True)
        self.provider = self.primary_config["provider"]

    def _fallback_chain(self) -> List[Dict]:
        chain = [self.primary_config]
        for name in LLM_FALLBACK_PROVIDERS:
            if name == self.primary_config["provider"]:
                continue
            config = _resolve_provider_config(name, required=False)
            if config:
                chain.append(config)
        return chain

    def _trim_chunks_to_budget(self, chunks: List[Dict]) -> List[Dict]:
        """
        Drop lowest-ranked chunks (chunks are expected to already be
        sorted by relevance) once the cumulative character count of
        retrieved text exceeds MAX_CONTEXT_CHARS. Set MAX_CONTEXT_CHARS=0
        to disable.
        """
        if MAX_CONTEXT_CHARS <= 0 or not chunks:
            return chunks

        kept = []
        running_total = 0
        for chunk in chunks:
            chunk_len = len(chunk.get("text", ""))
            if running_total + chunk_len > MAX_CONTEXT_CHARS and kept:
                # Keep at least one chunk even if it alone exceeds budget —
                # an answer with some context beats no context at all.
                break
            kept.append(chunk)
            running_total += chunk_len

        if len(kept) < len(chunks):
            logger.info(
                f"Trimmed context: {len(chunks)} -> {len(kept)} chunks "
                f"({running_total} chars, budget {MAX_CONTEXT_CHARS})"
            )
        return kept

    def _build_context(self, chunks: List[Dict]) -> str:
        if not chunks:
            return "No relevant context was found."
        parts = []
        for i, chunk in enumerate(chunks, start=1):
            doc_name = chunk.get("document_name", "unknown document")
            text = chunk.get("text", "")
            parts.append(f"[Source {i}: {doc_name}]\n{text}")
        return "\n\n".join(parts)

    def _build_prompt(self, query: str, chunks: List[Dict], system_prompt: Optional[str] = None) -> str:
        context = self._build_context(chunks)
        instructions = system_prompt or SYSTEM_PROMPT
        return f"""{instructions}

Context:
{context}

Question: {query}
Answer:"""

    def _call_provider(self, config: Dict, prompt: str, temperature: float, max_tokens: int) -> Tuple[str, Optional[Dict]]:
        """Returns (answer_text, usage_dict_or_None). usage_dict has
        prompt_tokens/completion_tokens/total_tokens when the provider
        reports them."""
        provider = config["provider"]
        if provider == "gemini":
            return self._call_gemini(prompt, temperature, max_tokens, config["api_key"], config["model"])
        elif provider == "anthropic":
            return self._call_anthropic(prompt, temperature, max_tokens, config["api_key"], config["model"])
        else:
            return self._call_openai_compatible(
                prompt, temperature, max_tokens, config["api_key"], config["model"], config["base_url"]
            )

    def _stream_provider(self, config: Dict, prompt: str, temperature: float, max_tokens: int) -> Iterator[str]:
        provider = config["provider"]
        if provider == "gemini":
            yield from self._stream_gemini(prompt, temperature, max_tokens, config["api_key"], config["model"])
        elif provider == "anthropic":
            yield from self._stream_anthropic(prompt, temperature, max_tokens, config["api_key"], config["model"])
        else:
            yield from self._stream_openai_compatible(
                prompt, temperature, max_tokens, config["api_key"], config["model"], config["base_url"]
            )

    def generate_answer(
        self,
        query: str,
        chunks: List[Dict],
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict:
        """
        Generate an answer to `query` grounded in the given `chunks`.
        Returns: {"answer": str, "sources": List[str], "provider_used": str,
                  "usage": {"prompt_tokens": int, "completion_tokens": int,
                            "total_tokens": int} or None,
                  "chunks_sent": int}

        Retrieved chunks are trimmed to MAX_CONTEXT_CHARS before building
        the prompt (see _trim_chunks_to_budget) — chunks_sent reports how
        many actually made it into the prompt, which may be fewer than
        len(chunks) if trimming occurred.
        """
        temp = DEFAULT_TEMPERATURE if temperature is None else temperature
        max_tok = MAX_OUTPUT_TOKENS if max_tokens is None else max_tokens

        trimmed_chunks = self._trim_chunks_to_budget(chunks)
        sources = list({c.get("document_name", "unknown") for c in trimmed_chunks})
        prompt = self._build_prompt(query, trimmed_chunks, system_prompt)

        chain = self._fallback_chain()
        last_error = None

        for i, config in enumerate(chain):
            try:
                answer_text, usage = self._call_provider(config, prompt, temp, max_tok)
                if i > 0:
                    logger.info(f"Answer generated via fallback provider '{config['provider']}' (primary failed)")
                return {
                    "answer": answer_text,
                    "sources": sources,
                    "provider_used": config["provider"],
                    "usage": usage,
                    "chunks_sent": len(trimmed_chunks),
                }
            except Exception as e:
                last_error = e
                logger.warning(f"Provider '{config['provider']}' failed: {e}")
                continue

        logger.error(f"All providers in the fallback chain failed. Last error: {last_error}")
        return {
            "answer": f"Sorry, I couldn't generate an answer — all configured providers failed. Last error: {last_error}",
            "sources": [],
            "provider_used": None,
            "usage": None,
            "chunks_sent": 0,
        }

    def generate_answer_stream(
        self,
        query: str,
        chunks: List[Dict],
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        """
        Same as generate_answer(), but yields answer text incrementally.
        Chunks are trimmed to MAX_CONTEXT_CHARS the same way. Usage
        reporting is not available for streaming responses (each
        provider's streaming API handles usage differently — accurately
        supporting all three would need separate work; not done here).
        """
        temp = DEFAULT_TEMPERATURE if temperature is None else temperature
        max_tok = MAX_OUTPUT_TOKENS if max_tokens is None else max_tokens

        trimmed_chunks = self._trim_chunks_to_budget(chunks)
        prompt = self._build_prompt(query, trimmed_chunks, system_prompt)

        chain = self._fallback_chain()
        last_error = None

        for i, config in enumerate(chain):
            yielded_anything = False
            try:
                for piece in self._stream_provider(config, prompt, temp, max_tok):
                    yielded_anything = True
                    yield piece
                if i > 0:
                    logger.info(f"Streamed via fallback provider '{config['provider']}' (primary failed)")
                return
            except Exception as e:
                last_error = e
                logger.warning(f"Provider '{config['provider']}' failed during streaming: {e}")
                if yielded_anything:
                    yield f"\n[Error: generation interrupted — {e}]"
                    return
                continue

        logger.error(f"All providers in the fallback chain failed during streaming. Last error: {last_error}")
        yield f"Sorry, I couldn't generate an answer — all configured providers failed. Last error: {last_error}"

    def _call_gemini(self, prompt: str, temperature: float, max_tokens: int, api_key: str, model: str) -> Tuple[str, Optional[Dict]]:
        import google.genai as genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        text = response.text.strip() if response.text else "No answer generated."
        usage = None
        if getattr(response, "usage_metadata", None):
            um = response.usage_metadata
            usage = {
                "prompt_tokens": um.prompt_token_count,
                "completion_tokens": um.candidates_token_count,
                "total_tokens": um.total_token_count,
            }
        return text, usage

    def _stream_gemini(self, prompt: str, temperature: float, max_tokens: int, api_key: str, model: str) -> Iterator[str]:
        import google.genai as genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        stream = client.models.generate_content_stream(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        for chunk in stream:
            if chunk.text:
                yield chunk.text

    def _call_anthropic(self, prompt: str, temperature: float, max_tokens: int, api_key: str, model: str) -> Tuple[str, Optional[Dict]]:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip() if response.content else "No answer generated."
        usage = None
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }
        return text, usage

    def _stream_anthropic(self, prompt: str, temperature: float, max_tokens: int, api_key: str, model: str) -> Iterator[str]:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield text

    def _call_openai_compatible(self, prompt: str, temperature: float, max_tokens: int, api_key: str, model: str, base_url: str) -> Tuple[str, Optional[Dict]]:
        import openai
        client = openai.OpenAI(api_key=api_key or "not-needed", base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content.strip() if response.choices else "No answer generated."
        usage = None
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return text, usage

    def _stream_openai_compatible(self, prompt: str, temperature: float, max_tokens: int, api_key: str, model: str, base_url: str) -> Iterator[str]:
        import openai
        client = openai.OpenAI(api_key=api_key or "not-needed", base_url=base_url)
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
