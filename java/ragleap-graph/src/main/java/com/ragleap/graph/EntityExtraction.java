package com.ragleap.graph;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Deterministic entity-name normalization and regex entity extraction,
 * ported from the Python ragleap-graph package.
 */
public final class EntityExtraction {
    private EntityExtraction() {
    }

    /** Single-word candidates dropped from regex extraction (sentence-initial words). */
    public static final Set<String> SENTENCE_INITIAL_STOPWORDS = Set.of(
            "What", "Who", "When", "Where", "Why", "How", "Which",
            "The", "This", "That", "These", "Those",
            "Is", "Are", "Was", "Were", "Do", "Does", "Did",
            "Can", "Could", "Would", "Should", "Will", "May", "Might");

    private static final String STRIP_CHARS = " \t\r\n.,;:!?()[]{}'\"";
    private static final int MAX_NAME_LENGTH = 120;
    private static final String NOT_WORD_AHEAD = "(?![\\p{L}\\p{Nd}\\p{Nl}\\p{No}_])";
    private static final String SPACE = "[\\t-\\r\\u001C-\\u0020\\u0085\\u00A0\\u1680\\u2000-\\u200A"
            + "\\u2028\\u2029\\u202F\\u205F\\u3000]";

    // The leading word boundary is checked by hand in findAll, because Java
    // word boundaries do not follow Python's Unicode rules.
    private static final Pattern ACRONYM = Pattern.compile("[A-Z]{2,}(?:-[A-Z0-9]+)?" + NOT_WORD_AHEAD);
    private static final Pattern PHRASE = Pattern.compile(
            "[A-Z][a-z]{2,}(?:" + SPACE + "+[A-Z][a-z]{2,}){0,2}" + NOT_WORD_AHEAD);

    /** Normalizes extracted entity text into a stable graph key; empty string if unusable. */
    public static String normalizeEntityName(String raw) {
        if (raw == null || raw.isEmpty()) {
            return "";
        }
        String name = PyText.stripChars(PyText.collapseWhitespace(raw), STRIP_CHARS);
        if (name.codePointCount(0, name.length()) < 3) {
            return "";
        }
        String normalized;
        if (PyText.isUpper(name)) {
            normalized = name;
        } else {
            StringBuilder sb = new StringBuilder();
            for (String part : name.split(" ")) {
                if (part.isEmpty()) {
                    continue;
                }
                if (sb.length() > 0) {
                    sb.append(' ');
                }
                sb.append(PyText.capitalize(part));
            }
            normalized = sb.toString();
        }
        return PyText.truncateCodePoints(normalized, MAX_NAME_LENGTH);
    }

    /** Extracts entity candidates (acronyms, capitalized phrases, optional domain terms). */
    public static List<String> extractEntityCandidates(String text, int maxEntities, List<String> domainTerms) {
        List<String> out = new ArrayList<>();
        if (text == null || text.isEmpty()) {
            return out;
        }
        List<String> candidates = new ArrayList<>(findAll(ACRONYM, text));
        for (String phrase : findAll(PHRASE, text)) {
            if (!SENTENCE_INITIAL_STOPWORDS.contains(phrase)) {
                candidates.add(phrase);
            }
        }
        if (domainTerms != null && !domainTerms.isEmpty()) {
            String lowerText = text.toLowerCase(Locale.ROOT);
            for (String term : domainTerms) {
                if (lowerText.contains(term.toLowerCase(Locale.ROOT))) {
                    candidates.add(term);
                }
            }
        }
        Set<String> seen = new HashSet<>();
        for (String cand : candidates) {
            String normalized = normalizeEntityName(cand);
            if (normalized.isEmpty()) {
                continue;
            }
            if (!seen.add(normalized.toLowerCase(Locale.ROOT))) {
                continue;
            }
            out.add(normalized);
            if (out.size() >= maxEntities) {
                break;
            }
        }
        return out;
    }

    public static List<String> extractEntityCandidates(String text) {
        return extractEntityCandidates(text, 12, null);
    }

    /** Extracts entity candidates from a user query string. */
    public static List<String> extractQueryEntities(String query, int maxEntities, List<String> domainTerms) {
        return extractEntityCandidates(query, maxEntities, domainTerms);
    }

    public static List<String> extractQueryEntities(String query) {
        return extractQueryEntities(query, 10, null);
    }

    private static List<String> findAll(Pattern pattern, String text) {
        List<String> out = new ArrayList<>();
        Matcher m = pattern.matcher(text);
        int from = 0;
        while (from <= text.length() && m.find(from)) {
            int s = m.start();
            if (s > 0 && PyText.isWord(text.codePointBefore(s))) {
                from = s + 1;
                continue;
            }
            out.add(text.substring(s, m.end()));
            from = m.end();
        }
        return out;
    }
}
