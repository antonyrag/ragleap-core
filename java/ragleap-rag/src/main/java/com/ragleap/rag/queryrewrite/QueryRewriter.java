package com.ragleap.rag.queryrewrite;

import com.ragleap.rag.generation.GenerationResult;
import com.ragleap.rag.generation.GenerationService;
import com.ragleap.rag.generation.ProviderConfig;
import com.ragleap.rag.vectorstore.SearchResult;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.StringReader;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Logger;

/**
 * Query rewriting/expansion for ragleap-rag - three selectable
 * strategies to improve retrieval quality. Java port of
 * ragleap-rag's query_rewrite.py. Grounded in established RAG
 * research (HyDE - Gao et al. 2022; RAG-Fusion/multi-query -
 * Rackauckas 2023).
 *
 * Honest limitation, carried over from the Python source: multi-query's
 * generated variants can be nearly identical and lacking in diversity -
 * it is not a guaranteed recall improvement, and it costs N retrieval
 * calls instead of one. contextualRewrite and hydeDocument each add
 * exactly one extra LLM call and zero extra retrieval calls.
 *
 * Every strategy is meant to fail open: if the rewrite LLM call fails,
 * retrieval should proceed using the original query. In practice,
 * GenerationService.generateAnswer() never throws - it swallows
 * provider failures into a GenerationResult whose answer() is a
 * "Sorry, all configured providers failed..." message. Since that
 * message is a non-blank string, it gets used AS the rewritten query
 * text rather than triggering the original-query fallback - this
 * matches the Python source's actual behavior (a truthy non-empty
 * string check, nothing more) exactly, even though it may look
 * surprising. Not "fixed" here - faithfully preserved and documented,
 * consistent with how this port has handled every other such quirk.
 */
public final class QueryRewriter {

    private static final Logger logger = Logger.getLogger(QueryRewriter.class.getName());

    private static final String REWRITE_SYSTEM_PROMPT =
            "Follow the instructions in the question below exactly. Do not add commentary, " +
            "explanation, or a preamble - respond with only what was asked for.";

    public static final String CONTEXTUAL_REWRITE_PROMPT =
            "Given the conversation history and a follow-up question, rewrite the follow-up " +
            "question to be a standalone question that includes all necessary context from the " +
            "history. Do not answer the question - only rewrite it. If the question is already " +
            "standalone, return it unchanged. Respond with ONLY the rewritten question, nothing else.\n\n" +
            "{history}\n" +
            "Follow-up question: {query}\n\n" +
            "Standalone question:";

    public static final String HYDE_PROMPT =
            "Write a short, plausible passage that would answer the following question, as if it " +
            "were an excerpt from a real document. Write confidently and specifically, even if " +
            "you're not certain of the real answer - this passage is used only to improve document " +
            "retrieval matching, it is never shown to the user.\n\n" +
            "Question: {query}\n\n" +
            "Passage:";

    public static final String MULTI_QUERY_PROMPT =
            "Generate {n} different phrasings of the following question, capturing different " +
            "angles or wordings a user might use to ask about the same underlying information " +
            "need. Respond with ONLY the alternative questions, one per line, no numbering or " +
            "extra text.\n\n" +
            "Original question: {query}\n\n" +
            "Alternative phrasings:";

    private QueryRewriter() {
        // Utility class - no instances, matches query_rewrite.py's module-level functions.
    }

    /**
     * One extra LLM call: rewrites a (possibly ambiguous, pronoun-laden)
     * follow-up question into a standalone question using conversation
     * history. Falls back to the original query if there's no history
     * to rewrite against.
     */
    public static QueryRewriteResult contextualRewrite(GenerationService generator, String query,
            String historyPrefix, ProviderConfig overrideProvider) {
        if (historyPrefix == null || historyPrefix.isEmpty()) {
            return new QueryRewriteResult(query, null);
        }
        String prompt = CONTEXTUAL_REWRITE_PROMPT.replace("{history}", historyPrefix).replace("{query}", query);
        try {
            GenerationResult result = generator.generateAnswer(prompt, List.of(), null, overrideProvider,
                    null, "", REWRITE_SYSTEM_PROMPT, null);
            String rewritten = result.answer() != null ? result.answer().strip() : "";
            return new QueryRewriteResult(rewritten.isEmpty() ? query : rewritten, result);
        } catch (Exception e) {
            logger.warning(() -> "Contextual query rewrite failed, using original query for retrieval: " + e.getMessage());
            return new QueryRewriteResult(query, null);
        }
    }

    /**
     * One extra LLM call: generates a hypothetical answer passage to
     * embed instead of the raw query for retrieval - HyDE (Gao et al.
     * 2022).
     */
    public static QueryRewriteResult hydeDocument(GenerationService generator, String query,
            ProviderConfig overrideProvider) {
        String prompt = HYDE_PROMPT.replace("{query}", query);
        try {
            GenerationResult result = generator.generateAnswer(prompt, List.of(), null, overrideProvider,
                    null, "", REWRITE_SYSTEM_PROMPT, null);
            String hypothetical = result.answer() != null ? result.answer().strip() : "";
            return new QueryRewriteResult(hypothetical.isEmpty() ? query : hypothetical, result);
        } catch (Exception e) {
            logger.warning(() -> "HyDE passage generation failed, using original query for retrieval: " + e.getMessage());
            return new QueryRewriteResult(query, null);
        }
    }

    /** One extra LLM call: generates up to 3 alternative phrasings of the query. */
    public static MultiQueryResult multiQueryVariants(GenerationService generator, String query,
            ProviderConfig overrideProvider) {
        return multiQueryVariants(generator, query, 3, overrideProvider);
    }

    /**
     * One extra LLM call: generates up to n alternative phrasings of
     * the query. Always includes the original query as the first
     * variant.
     */
    public static MultiQueryResult multiQueryVariants(GenerationService generator, String query, int n,
            ProviderConfig overrideProvider) {
        String prompt = MULTI_QUERY_PROMPT.replace("{n}", String.valueOf(n)).replace("{query}", query);
        try {
            GenerationResult result = generator.generateAnswer(prompt, List.of(), null, overrideProvider,
                    null, "", REWRITE_SYSTEM_PROMPT, null);
            String answer = result.answer() != null ? result.answer() : "";

            List<String> lines = new ArrayList<>();
            try (BufferedReader reader = new BufferedReader(new StringReader(answer))) {
                String rawLine;
                while ((rawLine = reader.readLine()) != null) {
                    String stripped = stripChars(rawLine, " -*\t");
                    if (!stripped.isEmpty()) {
                        lines.add(stripped);
                    }
                }
            } catch (IOException e) {
                // StringReader never actually throws - unreachable in practice.
            }

            List<String> variants = new ArrayList<>();
            variants.add(query);
            for (String line : lines) {
                if (!line.equalsIgnoreCase(query)) {
                    variants.add(line);
                }
            }
            List<String> trimmed = variants.size() > n ? new ArrayList<>(variants.subList(0, n)) : variants;
            return new MultiQueryResult(trimmed, result);
        } catch (Exception e) {
            logger.warning(() -> "Multi-query generation failed, using original query only: " + e.getMessage());
            return new MultiQueryResult(List.of(query), null);
        }
    }

    /** Strips any of the given characters from both ends of s - Java equivalent of Python's str.strip(chars). */
    private static String stripChars(String s, String chars) {
        int start = 0;
        int end = s.length();
        while (start < end && chars.indexOf(s.charAt(start)) >= 0) {
            start++;
        }
        while (end > start && chars.indexOf(s.charAt(end - 1)) >= 0) {
            end--;
        }
        return s.substring(start, end);
    }

    /** Merges multiple ranked chunk lists using Reciprocal Rank Fusion, with the standard k=60. */
    public static List<SearchResult> reciprocalRankFusion(List<List<SearchResult>> rankedLists) {
        return reciprocalRankFusion(rankedLists, 60);
    }

    /**
     * Merges multiple ranked chunk lists into one, using Reciprocal
     * Rank Fusion (Cormack, Clarke, Buettcher 2009) - the standard
     * merge technique for multi-query/RAG-Fusion retrieval.
     * Deduplicates by chunkId (falling back to (documentId,
     * chunkIndex) if a backend doesn't populate chunkId).
     *
     * Uses LinkedHashMap (preserves first-seen/insertion order) and a
     * stable sort, matching the Python source's dict-iteration-order +
     * stable-sorted() behavior exactly for tie-breaking among equal
     * scores.
     */
    public static List<SearchResult> reciprocalRankFusion(List<List<SearchResult>> rankedLists, int k) {
        Map<RrfKey, Double> scores = new LinkedHashMap<>();
        Map<RrfKey, SearchResult> chunkByKey = new LinkedHashMap<>();
        for (List<SearchResult> rankedList : rankedLists) {
            for (int rank = 0; rank < rankedList.size(); rank++) {
                SearchResult chunk = rankedList.get(rank);
                RrfKey key = keyFor(chunk);
                scores.merge(key, 1.0 / (k + rank + 1), Double::sum);
                chunkByKey.putIfAbsent(key, chunk);
            }
        }
        List<RrfKey> rankedKeys = new ArrayList<>(scores.keySet());
        rankedKeys.sort((a, b) -> Double.compare(scores.get(b), scores.get(a)));

        List<SearchResult> result = new ArrayList<>();
        for (RrfKey key : rankedKeys) {
            result.add(chunkByKey.get(key));
        }
        return result;
    }

    private static RrfKey keyFor(SearchResult chunk) {
        if (chunk.chunkId() != null) {
            return new RrfKey(chunk.chunkId(), null, 0);
        }
        return new RrfKey(null, chunk.documentId(), chunk.chunkIndex());
    }

    private record RrfKey(String chunkId, String documentId, int chunkIndex) {
    }
}
