"""
Answer Generation Service for RagLeap Core
Uses Google Gemini to generate a grounded answer from retrieved chunks.
Bring-your-own-key only — no system key, no fallback.
"""
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

GEMINI_CHAT_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = """You are a helpful assistant that answers questions using ONLY the provided context.
If the answer is not in the context, say clearly that you don't have that information — do not make things up.
Always be concise and cite which document your answer came from when possible."""


class GenerationService:
    """
    Generates a grounded answer using Gemini, given a query and retrieved chunks.
    """

    def __init__(self):
        self.model = GEMINI_CHAT_MODEL
        self.api_key = os.environ.get("GEMINI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. RagLeap Core requires your own "
                "Gemini API key — get one at https://aistudio.google.com/apikey "
                "and add it to your .env file. There is no system-provided key."
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
            import google.genai as genai
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            answer_text = response.text.strip() if response.text else "No answer generated."

            return {
                "answer": answer_text,
                "sources": sources,
            }
        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return {
                "answer": f"Sorry, I couldn't generate an answer due to an error: {e}",
                "sources": [],
            }
