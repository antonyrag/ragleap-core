package com.ragleap.rag.sanitization;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Content sanitization and injection-risk detection for ragleap-rag.
 * Java port of ragleap-rag's sanitization.py.
 *
 * Honest scope, same as the Python source: this reduces risk, it does
 * not eliminate it. Prompt injection via retrieved content is an open
 * research problem — pattern-based detection will miss novel or
 * obfuscated attempts. Treat flagged content as a signal to review,
 * not a guarantee of safety.
 */
public final class ContentSanitizer {

    private ContentSanitizer() {
    }

    public static final int DEFAULT_MAX_CHUNK_LENGTH = 50_000;

    // Common prompt-injection trigger phrases. Heuristic, not exhaustive —
    // a determined attacker can rephrase around any fixed list.
    private static final String[] INJECTION_PATTERNS = {
            "ignore (all )?(previous|prior|above) instructions",
            "disregard (all )?(previous|prior|above) instructions",
            "you are now",
            "new instructions:",
            "system prompt:",
            "\\bsystem:\\s",
            "forget (everything|all) (you|that)",
            "reveal your (system prompt|instructions)",
            "act as if",
            "do not (follow|obey) (your|the) (previous|original) instructions",
    };

    private static final List<Pattern> COMPILED_PATTERNS = compilePatterns();

    private static List<Pattern> compilePatterns() {
        List<Pattern> patterns = new ArrayList<>();
        for (String p : INJECTION_PATTERNS) {
            patterns.add(Pattern.compile(p, Pattern.CASE_INSENSITIVE));
        }
        return Collections.unmodifiableList(patterns);
    }

    /**
     * Strip null bytes, control characters (except newline/tab), and
     * invisible/zero-width Unicode characters. Safe to call on any text —
     * normal content is unaffected.
     *
     * Mirrors Python's check against unicodedata categories Cc (control)
     * and Cf (format, which covers zero-width/invisible characters) —
     * Java's Character.CONTROL and Character.FORMAT are the same
     * Unicode category classes.
     */
    public static String sanitizeText(String text) {
        if (text == null || text.isEmpty()) {
            return text;
        }

        StringBuilder cleaned = new StringBuilder(text.length());
        text.codePoints().forEach(cp -> {
            if (cp == '\n' || cp == '\t') {
                cleaned.appendCodePoint(cp);
                return;
            }
            int type = Character.getType(cp);
            if (type != Character.CONTROL && type != Character.FORMAT) {
                cleaned.appendCodePoint(cp);
            }
        });
        return cleaned.toString();
    }

    /**
     * Return a list of matched suspicious phrases, if any. Empty list
     * means no known pattern matched — not a guarantee the content is
     * safe, just that it didn't match this heuristic list.
     */
    public static List<String> detectInjectionRisk(String text) {
        if (text == null || text.isEmpty()) {
            return List.of();
        }

        List<String> matches = new ArrayList<>();
        for (Pattern pattern : COMPILED_PATTERNS) {
            Matcher matcher = pattern.matcher(text);
            if (matcher.find()) {
                matches.add(matcher.group(0));
            }
        }
        return matches;
    }

    /**
     * Return true if text is within the allowed length.
     * Counts Unicode code points (matching Python's len()), not UTF-16
     * code units — String.length() would overcount any character outside
     * the Basic Multilingual Plane (e.g. many emoji), making this check
     * stricter than the Python original for such input.
     */
    public static boolean checkLength(String text) {
        return checkLength(text, DEFAULT_MAX_CHUNK_LENGTH);
    }

    public static boolean checkLength(String text, int maxLength) {
        int codePointCount = text.codePointCount(0, text.length());
        return codePointCount <= maxLength;
    }
}
