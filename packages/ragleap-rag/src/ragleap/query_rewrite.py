"""
Query rewriting/expansion for ragleap-rag - three selectable strategies
to improve retrieval quality. Grounded in established RAG research
(HyDE - Gao et al. 2022; RAG-Fusion/multi-query - Rackauckas 2023) and
current 2026 production practice - a cited production case study (mid-
size SaaS customer support KB) used "query rewriting via a small LLM
call" as part of a stack that cut wrong-answer rate from 22% to 4%.

Honest limitation, stated plainly rather than oversold: multi_query's
generated variants can be "nearly identical and lacking in diversity"
(a documented finding in the broader RAG literature, not unique to
this implementation) - it is not a guaranteed recall improvement, and
it costs N retrieval calls instead of one. contextual and hyde each
add exactly one extra LLM call and zero extra retrieval calls - if you
want the cheap, fast option, use one of those instead.

Every strategy fails open: if the rewrite LLM call itself fails for
any reason, retrieval proceeds using the original, unmodified query -
a broken rewrite step should never be able to break retrieval entirely.
"""
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CONTEXTUAL_REWRITE_PROMPT = """Given the conversation history and a follow-up question, rewrite the follow-up question to be a standalone question that includes all necessary context from the history. Do not answer the question - only rewrite it. If the question is already standalone, return it unchanged. Respond with ONLY the rewritten question, nothing else.

{history}
Follow-up question: {query}

Standalone question:"""

HYDE_PROMPT = """Write a short, plausible passage that would answer the following question, as if it were an excerpt from a real document. Write confidently and specifically, even if you're not certain of the real answer - this passage is used only to improve document retrieval matching, it is never shown to the user.

Question: {query}

Passage:"""

MULTI_QUERY_PROMPT = """Generate {n} different phrasings of the following question, capturing different angles or wordings a user might use to ask about the same underlying information need. Respond with ONLY the alternative questions, one per line, no numbering or extra text.

Original question: {query}

Alternative phrasings:"""


def contextual_rewrite(generator, query: str, history_prefix: str, override_provider=None) -> Tuple[str, Optional[Dict]]:
    """One extra LLM call: rewrites a (possibly ambiguous, pronoun-laden)
    follow-up question into a standalone question using conversation
    history. Falls back to the original query if there's no history to
    rewrite against, or if the rewrite call fails for any reason.

    Returns (query_to_use_for_retrieval, raw_generate_answer_result_or_None) -
    the second element lets the caller record real token cost for this
    call, or is None when no LLM call was made at all (no history).
    """
    if not history_prefix:
        return query, None
    prompt = CONTEXTUAL_REWRITE_PROMPT.format(history=history_prefix, query=query)
    try:
        result = generator.generate_answer(
            query=prompt, chunks=[], history_prefix="", override_provider=override_provider,
            system_prompt="Follow the instructions in the question below exactly. Do not add commentary, explanation, or a preamble - respond with only what was asked for.",
        )
        rewritten = (result.get("answer") or "").strip()
        return (rewritten if rewritten else query), result
    except Exception as e:
        logger.warning(f"Contextual query rewrite failed, using original query for retrieval: {e}")
        return query, None


def hyde_document(generator, query: str, override_provider=None) -> Tuple[str, Optional[Dict]]:
    """One extra LLM call: generates a hypothetical answer passage to
    embed instead of the raw query for retrieval - HyDE (Gao et al.
    2022). Falls back to the original query text on failure.

    Returns (text_to_embed_for_retrieval, raw_generate_answer_result_or_None).
    """
    prompt = HYDE_PROMPT.format(query=query)
    try:
        result = generator.generate_answer(
            query=prompt, chunks=[], history_prefix="", override_provider=override_provider,
            system_prompt="Follow the instructions in the question below exactly. Do not add commentary, explanation, or a preamble - respond with only what was asked for.",
        )
        hypothetical = (result.get("answer") or "").strip()
        return (hypothetical if hypothetical else query), result
    except Exception as e:
        logger.warning(f"HyDE passage generation failed, using original query for retrieval: {e}")
        return query, None


def multi_query_variants(generator, query: str, n: int = 3, override_provider=None) -> Tuple[List[str], Optional[Dict]]:
    """One extra LLM call: generates up to n alternative phrasings of
    the query. Always includes the original query as the first variant.
    Falls back to [query] alone on failure.

    Returns (list_of_query_variants, raw_generate_answer_result_or_None).
    """
    prompt = MULTI_QUERY_PROMPT.format(n=n, query=query)
    try:
        result = generator.generate_answer(
            query=prompt, chunks=[], history_prefix="", override_provider=override_provider,
            system_prompt="Follow the instructions in the question below exactly. Do not add commentary, explanation, or a preamble - respond with only what was asked for.",
        )
        lines = [line.strip(" -*\t") for line in (result.get("answer") or "").splitlines()]
        lines = [line for line in lines if line]
        variants = [query] + [line for line in lines if line.lower() != query.lower()]
        return variants[:n] if len(variants) > n else variants, result
    except Exception as e:
        logger.warning(f"Multi-query generation failed, using original query only: {e}")
        return [query], None


def reciprocal_rank_fusion(ranked_lists: List[List[Dict]], k: int = 60) -> List[Dict]:
    """Merges multiple ranked chunk lists into one, using Reciprocal
    Rank Fusion (Cormack, Clarke, Buettcher 2009) - the standard merge
    technique for multi-query/RAG-Fusion retrieval. Deduplicates by
    chunk_id (falling back to (document_id, chunk_index) if a backend
    doesn't populate chunk_id)."""
    scores: Dict = {}
    chunk_by_key: Dict = {}
    for ranked_list in ranked_lists:
        for rank, chunk in enumerate(ranked_list):
            key = chunk.get("chunk_id") or (chunk.get("document_id"), chunk.get("chunk_index"))
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            chunk_by_key.setdefault(key, chunk)
    ranked_keys = sorted(scores.keys(), key=lambda key: scores[key], reverse=True)
    return [chunk_by_key[key] for key in ranked_keys]
