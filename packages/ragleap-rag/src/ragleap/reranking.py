"""
Cross-encoder reranking for ragleap-rag.
Optional — requires the [rerank] extra (onnxruntime + tokenizers +
huggingface_hub). Runs a quantized ONNX cross-encoder on CPU - no
torch, no CUDA dependency. The base package works fully without this;
reranking is strictly opt-in.

Model files (~23MB, int8-quantized) download once on first use and
are cached by huggingface_hub (respects the HF_HOME env var, defaults
to ~/.cache/huggingface) - subsequent uses load from local cache.
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

DEFAULT_RERANK_MODEL_REPO = "Xenova/ms-marco-MiniLM-L-6-v2"
DEFAULT_MODEL_FILE = "onnx/model_quantized.onnx"
DEFAULT_TOKENIZER_FILE = "tokenizer.json"


class RerankerService:
    """
    Reorders retrieved chunks by genuine query-document relevance using
    a cross-encoder, rather than relying solely on the initial retrieval
    score (cosine similarity / RRF fusion). The cross-encoder scores
    each (query, chunk) pair jointly, which is slower but more accurate
    than the bi-encoder scoring used for initial retrieval.

    Runs on ONNX Runtime (CPU only) rather than torch/sentence-transformers
    - avoids a 2GB+ torch+CUDA install for what is, for this model size,
    pure CPU inference. Scores one (query, chunk) pair per inference call
    rather than batching all pairs together - a known simplification, not
    a bottleneck at typical candidate-pool sizes (top_k*4, usually ~20).
    """

    def __init__(self, model_repo: str = DEFAULT_RERANK_MODEL_REPO):
        self.model_repo = model_repo
        self._session = None  # lazy-loaded ONNX runtime session
        self._tokenizer = None  # lazy-loaded tokenizer

    def _ensure_model_loaded(self):
        if self._session is not None:
            return
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
            from huggingface_hub import hf_hub_download
        except ImportError:
            raise ImportError(
                "Reranking requires the 'rerank' extra. Install it with: "
                "pip install ragleap-rag[rerank]"
            )

        logger.info(f"Loading reranker model '{self.model_repo}' (downloads once, cached after)...")
        model_path = hf_hub_download(self.model_repo, DEFAULT_MODEL_FILE)
        tokenizer_path = hf_hub_download(self.model_repo, DEFAULT_TOKENIZER_FILE)

        self._session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=512)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        logger.info("Reranker model loaded (ONNX Runtime, CPU)")

    def _score_pair(self, query: str, text: str) -> float:
        import numpy as np
        encoding = self._tokenizer.encode(query, text)
        outputs = self._session.run(None, {
            "input_ids": np.array([encoding.ids], dtype=np.int64),
            "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
            "token_type_ids": np.array([encoding.type_ids], dtype=np.int64),
        })
        return float(outputs[0][0][0])

    def rerank(self, query: str, chunks: List[Dict], top_k: int) -> List[Dict]:
        """
        Rerank chunks by cross-encoder relevance to query, return the
        top_k highest-scoring chunks. Adds a 'rerank_score' field to
        each returned chunk. Chunks list is returned as-is if empty.
        """
        if not chunks:
            return chunks

        self._ensure_model_loaded()

        for chunk in chunks:
            chunk["rerank_score"] = round(self._score_pair(query, chunk["text"]), 4)

        reranked = sorted(chunks, key=lambda c: c["rerank_score"], reverse=True)

        logger.info(f"Reranked {len(chunks)} candidates -> top {min(top_k, len(reranked))}")
        return reranked[:top_k]
