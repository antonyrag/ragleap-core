package com.ragleap.graph;

import java.util.Locale;

/**
 * Small helpers that reproduce Python string behaviour which Java does not
 * offer directly: the whitespace set, regex word characters, isupper and
 * capitalize. Known gap: a few rare Greek letters with an iota subscript
 * are title-cased differently from Python.
 */
final class PyText {
    private PyText() {
    }

    /** True for the characters Python treats as whitespace. */
    static boolean isSpace(int cp) {
        return (cp >= 0x09 && cp <= 0x0D) || (cp >= 0x1C && cp <= 0x20) || cp == 0x85 || cp == 0xA0
                || cp == 0x1680 || (cp >= 0x2000 && cp <= 0x200A) || cp == 0x2028 || cp == 0x2029
                || cp == 0x202F || cp == 0x205F || cp == 0x3000;
    }

    /** True for the characters Python treats as word characters in a regex. */
    static boolean isWord(int cp) {
        if (cp == '_') {
            return true;
        }
        int t = Character.getType(cp);
        return Character.isLetter(cp) || t == Character.DECIMAL_DIGIT_NUMBER
                || t == Character.LETTER_NUMBER || t == Character.OTHER_NUMBER;
    }

    /** Replaces every run of whitespace with a single space. */
    static String collapseWhitespace(String s) {
        StringBuilder sb = new StringBuilder(s.length());
        boolean inSpace = false;
        for (int i = 0; i < s.length();) {
            int cp = s.codePointAt(i);
            i += Character.charCount(cp);
            if (isSpace(cp)) {
                if (!inSpace) {
                    sb.append(' ');
                }
                inSpace = true;
            } else {
                sb.appendCodePoint(cp);
                inSpace = false;
            }
        }
        return sb.toString();
    }

    /** Strips any of the given (BMP) characters from both ends. */
    static String stripChars(String s, String chars) {
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

    /** Python isupper: at least one cased character and none of them lower or title case. */
    static boolean isUpper(String s) {
        boolean cased = false;
        for (int i = 0; i < s.length();) {
            int cp = s.codePointAt(i);
            i += Character.charCount(cp);
            if (Character.isLowerCase(cp) || Character.isTitleCase(cp)) {
                return false;
            }
            if (Character.isUpperCase(cp)) {
                cased = true;
            }
        }
        return cased;
    }

    /** Python capitalize: title-case the first character, lower-case the rest. */
    static String capitalize(String s) {
        if (s.isEmpty()) {
            return s;
        }
        int first = s.codePointAt(0);
        String head = titleFirst(first);
        String firstLower = new String(Character.toChars(first)).toLowerCase(Locale.ROOT);
        String lowered = s.toLowerCase(Locale.ROOT);
        return head + lowered.substring(firstLower.length());
    }

    /** Keeps at most max code points. */
    static String truncateCodePoints(String s, int max) {
        if (s.codePointCount(0, s.length()) <= max) {
            return s;
        }
        return s.substring(0, s.offsetByCodePoints(0, max));
    }

    private static String titleFirst(int cp) {
        if (cp == 0x0149) {
            return "\u02BCN";
        }
        if (Character.isTitleCase(cp)) {
            return new String(Character.toChars(cp));
        }
        int title = Character.toTitleCase(cp);
        if (title != cp) {
            return new String(Character.toChars(title));
        }
        String upper = new String(Character.toChars(cp)).toUpperCase(Locale.ROOT);
        int firstUpper = upper.codePointAt(0);
        int firstLen = Character.charCount(firstUpper);
        return new String(Character.toChars(firstUpper)) + upper.substring(firstLen).toLowerCase(Locale.ROOT);
    }
}
