package com.ragleap.rag.parsers;

/**
 * Python-compatible whitespace helpers. Python's str.strip() and str.isspace()
 * treat non-breaking and other Unicode space separators as whitespace; Java's
 * String.strip() and isBlank() do not.
 */
final class PyText {

    private PyText() {
    }

    static boolean isSpace(char c) {
        return Character.isWhitespace(c) || Character.isSpaceChar(c) || c == (char) 0x85;
    }

    static String strip(String s) {
        int start = 0;
        int end = s.length();
        while (start < end && isSpace(s.charAt(start))) {
            start++;
        }
        while (end > start && isSpace(s.charAt(end - 1))) {
            end--;
        }
        return s.substring(start, end);
    }

    static boolean isBlank(String s) {
        for (int i = 0; i < s.length(); i++) {
            if (!isSpace(s.charAt(i))) {
                return false;
            }
        }
        return true;
    }
}
