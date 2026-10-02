package com.ragleap.rag.parsers;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Expected values were cross-checked against the real striprtf library
 * (the one Python's parsers.py uses) on the same inputs.
 */
class RtfConverterTest {

    private static String rtf(String s) {
        return RtfConverter.rtfToText(s);
    }

    @Test void plainText() {
        assertEquals("ragleapmarker", rtf("{\\rtf1\\ansi ragleapmarker}"));
    }

    @Test void parBecomesNewline() {
        assertEquals("Hello\nWorld", rtf("{\\rtf1\\ansi Hello\\par World}"));
    }

    @Test void destinationGroupsAreSkipped() {
        assertEquals("Visible", rtf("{\\rtf1\\ansi{\\fonttbl{\\f0 Arial;}}Visible}"));
    }

    @Test void hexEscapeUsesDeclaredCodePage() {
        assertEquals("caf\u00e9", rtf("{\\rtf1\\ansi\\ansicpg1252 caf\\'e9}"));
    }

    @Test void multiByteHexEscapesAreDecodedTogether() {
        assertEquals("\u00e9", rtf("{\\rtf1\\ansi\\ansicpg65001 \\'c3\\'a9}"));
    }

    @Test void unicodeEscapeSkipsTheFallbackCharacter() {
        assertEquals("\u20ac", rtf("{\\rtf1\\ansi\\uc1 \\u8364?}"));
    }

    @Test void unicodeEscapeWithUcZeroSkipsNothing() {
        assertEquals("\u00e9x", rtf("{\\rtf1\\ansi\\uc0 \\u233 x}"));
    }

    @Test void negativeUnicodeEscapesFormASurrogatePair() {
        assertEquals("\uD83D\uDE00", rtf("{\\rtf1\\ansi \\u-10179?\\u-8704?}"));
    }

    @Test void tableCellsAndRows() {
        assertEquals("A|B|\n", rtf("{\\rtf1\\ansi A\\cell B\\cell\\row}"));
    }

    @Test void specialCharacters() {
        assertEquals("a\tb\u2014c{d}\u00a0e", rtf("{\\rtf1\\ansi a\\tab b\\emdash c\\{d\\}\\~e}"));
    }

    @Test void hyperlinkDestinationIsAppendedAfterTheLinkText() {
        String in = "{\\rtf1\\ansi {\\field{\\*\\fldinst{HYPERLINK \"http://x.com\"}}{\\fldrslt link text}}}";
        assertEquals("link text(\"http://x.com\")", rtf(in));
    }

    @Test void rawNewlinesInTheSourceAreIgnored() {
        assertEquals("ab", rtf("{\\rtf1\\ansi a\r\nb}"));
    }

    @Test void hexEscapePendingAtTheVeryEndIsDroppedLikeStriprtf() {
        assertEquals("caf", rtf("{\\rtf1\\ansi caf\\'e9"));
    }

    @Test void undecodableByteIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> rtf("{\\rtf1\\ansi \\'81}"));
    }

    @Test void ucWithoutANumberIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> rtf("{\\rtf1\\ansi\\uc x}"));
    }

    @Test void unbalancedClosingBraceDoesNotCrash() {
        assertEquals("", rtf("}abc"));
    }

    // ---- through DocumentParser ----

    @Test void documentParserDispatchesRtf() {
        byte[] raw = "{\\rtf1\\ansi ragleapmarker}".getBytes(StandardCharsets.UTF_8);
        assertTrue(DocumentParser.extractText("a.rtf", raw).contains("ragleapmarker"));
        assertTrue(DocumentParser.extractText("A.RTF", raw).contains("ragleapmarker"));
    }
}
