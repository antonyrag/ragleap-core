"""
Text Chunking for ragleap-rag.
"""
import logging
from typing import List

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 50


class TextChunker:
    """Splits documents into overlapping chunks for embedding and retrieval."""

    def __init__(self, chunk_size: int = None, chunk_overlap: int = None):
        self.chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or DEFAULT_CHUNK_OVERLAP

        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("Chunk overlap must be less than chunk size")

        logger.info(f"Initialized TextChunker: size={self.chunk_size}, overlap={self.chunk_overlap}")

    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace tokenization."""
        return text.split()

    def chunk_text(self, text: str) -> List[dict]:
        """
        Split text into overlapping chunks with metadata.
        Returns a list of dicts with: text, chunk_index, token_count
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for chunking")
            return []

        tokens = self._tokenize(text)
        if len(tokens) == 0:
            logger.warning("No tokens extracted from text")
            return []

        chunks = []
        step = self.chunk_size - self.chunk_overlap
        chunk_index = 0

        for start in range(0, len(tokens), step):
            end = min(start + self.chunk_size, len(tokens))
            chunk_tokens = tokens[start:end]
            chunk_text_content = " ".join(chunk_tokens)

            chunks.append({
                "text": chunk_text_content,
                "chunk_index": chunk_index,
                "token_count": len(chunk_tokens),
            })
            chunk_index += 1

            if end == len(tokens):
                break

        logger.info(f"Chunked text into {len(chunks)} chunks")
        return chunks


def create_chunker(chunk_size: int = None, chunk_overlap: int = None) -> TextChunker:
    return TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
