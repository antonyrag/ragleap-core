package com.ragleap.rag.parsers;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** Focused checks; the broad behaviour is verified against real Python by PythonParityFixturesTest. */
class EmlExtractorTest {

    private static String eml(String s) {
        return DocumentParser.extractText("a.eml", s.getBytes(StandardCharsets.ISO_8859_1));
    }

    @Test void quotedPrintableFollowsBinasciiRules() {
        byte[] out = EmlExtractor.decodeQuotedPrintable("a=3Db =ZZ x=\r\n y=\n".getBytes(StandardCharsets.ISO_8859_1));
        assertEquals("a=b =ZZ x y", new String(out, StandardCharsets.ISO_8859_1));
    }

    @Test void unpaddedBase64BodyIsDecoded() {
        assertEquals("From: a@b.c\nTo: \nSubject: \nhello",
                eml("From: a@b.c\nContent-Transfer-Encoding: base64\n\naGVsbG8"));
    }

    @Test void adjacentEncodedWordsDropTheWhitespaceBetweenThem() {
        assertEquals("ab plain", EmlExtractor.unstructured("=?utf-8?q?a?= =?utf-8?q?b?= plain"));
    }

    @Test void unknownBodyCharsetIsRejectedWithPythonsMessage() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> eml("From: a@b.c\nContent-Type: text/plain; charset=x-unknown\n\nhi"));
        assertEquals("unknown encoding: x-unknown", ex.getMessage());
    }

    @Test void unterminatedMultipartStripsTheLastPartsTrailingNewline() {
        String m = "From: a@b.c\nContent-Type: multipart/alternative; boundary=\"B\"\n\n--B\nContent-Type: text/plain\n\nplain body\n";
        assertEquals("From: a@b.c\nTo: \nSubject: \nplain body", eml(m));
    }

    @Test void encodedWordWithUnknownCharsetIsDecodedAsAscii() {
        assertEquals("abc text", EmlExtractor.unstructured("=?x-bogus?q?abc?= text"));
    }

    @Test void dispatchIsCaseInsensitive() {
        byte[] raw = "From: a@b.c\n\nbody".getBytes(StandardCharsets.ISO_8859_1);
        assertEquals("From: a@b.c\nTo: \nSubject: \nbody", DocumentParser.extractText("A.EML", raw));
    }
}
