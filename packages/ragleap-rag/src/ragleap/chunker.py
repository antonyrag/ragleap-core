"""
Text Chunking for ragleap-rag.
"""
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False

_encoding_cache: Dict[str, "tiktoken.Encoding"] = {}


def _real_token_count(text: str, model: str = "cl100k_base") -> Tuple[int, bool]:
    """
    Real LLM token count via tiktoken when available; falls back to a
    whitespace-split word count with is_exact=False when tiktoken isn't
    installed or its encoding can't be loaded (e.g. no network egress
    to fetch the BPE rank file on first use). Never reports the
    fallback estimate as exact -- that would reintroduce the same
    silent-inaccuracy problem this fix closes.
    """
    if _TIKTOKEN_AVAILABLE:
        try:
            if model not in _encoding_cache:
                _encoding_cache[model] = tiktoken.get_encoding(model)
            return len(_encoding_cache[model].encode(text)), True
        except Exception as e:
            logger.warning(f"tiktoken encoding unavailable ({e}); falling back to word count")
    return len(text.split()), False

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

            token_count, token_count_is_exact = _real_token_count(chunk_text_content)
            chunks.append({
                "text": chunk_text_content,
                "chunk_index": chunk_index,
                "token_count": token_count,
                "token_count_is_exact": token_count_is_exact,
            })
            chunk_index += 1

            if end == len(tokens):
                break

        logger.info(f"Chunked text into {len(chunks)} chunks")
        return chunks


def create_chunker(chunk_size: int = None, chunk_overlap: int = None) -> TextChunker:
    return TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
