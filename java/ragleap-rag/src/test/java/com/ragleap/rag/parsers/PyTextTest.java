package com.ragleap.rag.parsers;

import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Regression tests: Python's strip() treats non-breaking spaces as whitespace. */
class PyTextTest {

    @Test void stripRemovesNonBreakingAndUnicodeSpaces() {
        assertEquals("x", PyText.strip("\u00A0 \u2003x\u2028 \u0085"));
    }

    @Test void isBlankIsTrueForNonBreakingSpaceOnly() {
        assertTrue(PyText.isBlank("\u00A0\u00A0"));
        assertFalse(PyText.isBlank("\u00A0a"));
    }

    @Test void subtitleLinesContainingOnlyNonBreakingSpaceAreDropped() {
        byte[] raw = "a\n\u00A0\nb\n".getBytes(StandardCharsets.UTF_8);
        assertEquals("a\nb", DocumentParser.extractText("x.vtt", raw));
    }

    @Test void zipSkipsFilesWhoseTextIsOnlyNonBreakingSpaces() throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        try (ZipOutputStream zos = new ZipOutputStream(bos)) {
            zos.putNextEntry(new ZipEntry("blank.txt"));
            zos.write("\u00A0".getBytes(StandardCharsets.UTF_8));
            zos.closeEntry();
            zos.putNextEntry(new ZipEntry("good.txt"));
            zos.write("good".getBytes(StandardCharsets.UTF_8));
            zos.closeEntry();
        }
        assertEquals("[File: good.txt]\ngood", DocumentParser.extractText("x.zip", bos.toByteArray()));
    }
}
