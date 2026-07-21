"""
Cross-encoder reranking for ragleap-rag.
Optional — requires the [rerank] extra (sentence-transformers). The
base package works fully without this; reranking is strictly opt-in.
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class RerankerService:
    """
    Reorders retrieved chunks by genuine query-document relevance using
    a cross-encoder, rather than relying solely on the initial retrieval
    score (cosine similarity / RRF fusion). The cross-encoder scores
    each (query, chunk) pair jointly, which is slower but more accurate
    than the bi-encoder scoring used for initial retrieval.
    """

    def __init__(self, model_name: str = DEFAULT_RERANK_MODEL):
        self.model_name = model_name
        self._model = None  # lazy-loaded on first rerank() call

    def _ensure_model_loaded(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            raise ImportError(
                "Reranking requires the 'rerank' extra. Install it with: "
                "pip install ragleap-rag[rerank]"
            )
        logger.info(f"Loading cross-encoder model '{self.model_name}' (first use only)...")
        self._model = CrossEncoder(self.model_name)
        logger.info("Cross-encoder model loaded")

    def rerank(self, query: str, chunks: List[Dict], top_k: int) -> List[Dict]:
        """
        Rerank chunks by cross-encoder relevance to query, return the
        top_k highest-scoring chunks. Adds a 'rerank_score' field to
        each returned chunk. Chunks list is returned as-is (unranked
        truncation to top_k) if it's empty or reranking fails.
        """
        if not chunks:
            return chunks

        self._ensure_model_loaded()

        pairs = [(query, c["text"]) for c in chunks]
        scores = self._model.predict(pairs)

        for chunk, score in zip(chunks, scores):
            chunk["rerank_score"] = round(float(score), 4)

        reranked = sorted(chunks, key=lambda c: c["rerank_score"], reverse=True)

        logger.info(f"Reranked {len(chunks)} candidates -> top {min(top_k, len(reranked))}")
        return reranked[:top_k]
