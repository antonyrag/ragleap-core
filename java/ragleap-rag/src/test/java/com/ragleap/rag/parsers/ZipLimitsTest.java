package com.ragleap.rag.parsers;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Mirrors Python's test_parser_limits.py; the exact messages are also checked against real Python fixtures. */
class ZipLimitsTest {

    @AfterEach
    void resetLimits() {
        DocumentParser.setZipLimits(DocumentParser.DEFAULT_MAX_ZIP_MEMBERS, DocumentParser.DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES);
    }

    private static byte[] zipBytes(Map<String, byte[]> entries) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        try (ZipOutputStream z = new ZipOutputStream(bos)) {
            for (Map.Entry<String, byte[]> e : entries.entrySet()) {
                z.putNextEntry(new ZipEntry(e.getKey()));
                z.write(e.getValue());
                z.closeEntry();
            }
        }
        return bos.toByteArray();
    }

    private static byte[] zipText(String... namesAndContents) throws IOException {
        Map<String, byte[]> m = new LinkedHashMap<>();
        for (int i = 0; i < namesAndContents.length; i += 2) {
            m.put(namesAndContents[i], namesAndContents[i + 1].getBytes(StandardCharsets.UTF_8));
        }
        return zipBytes(m);
    }

    /** Overwrites the declared uncompressed size in the data descriptor and the central directory. */
    private static byte[] forgeUncompressedSize(byte[] zip, int newSize) {
        byte[] out = zip.clone();
        ByteBuffer b = ByteBuffer.wrap(out).order(ByteOrder.LITTLE_ENDIAN);
        int patched = 0;
        for (int i = 0; i + 28 <= out.length; i++) {
            int sig = b.getInt(i);
            if (sig == 0x08074b50) {
                b.putInt(i + 12, newSize);
                patched++;
            } else if (sig == 0x02014b50) {
                b.putInt(i + 24, newSize);
                patched++;
            }
        }
        assertEquals(2, patched, "expected one data descriptor and one central directory header");
        return out;
    }

    @Test void defaultsMatchPython() {
        assertEquals(1000, DocumentParser.DEFAULT_MAX_ZIP_MEMBERS);
        assertEquals(100L * 1024 * 1024, DocumentParser.DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES);
    }

    @Test void archiveWithinLimitsStillExtracts() throws IOException {
        String out = DocumentParser.extractText("a.zip", zipText("a.txt", "alpha", "b.txt", "beta"));
        assertEquals("[File: a.txt]\nalpha\n\n[File: b.txt]\nbeta", out);
    }

    @Test void tooManyMembersIsRejectedWithPythonsMessage() throws IOException {
        DocumentParser.setZipLimits(3, DocumentParser.DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES);
        byte[] zip = zipText("0.txt", "x", "1.txt", "x", "2.txt", "x", "3.txt", "x", "4.txt", "x");
        ZipLimitException ex = assertThrows(ZipLimitException.class, () -> DocumentParser.extractText("a.zip", zip));
        assertEquals("Archive has 5 members (limit 3).", ex.getMessage());
    }

    @Test void exactlyAtTheMemberLimitPassesAndOneMoreFails() throws IOException {
        DocumentParser.setZipLimits(3, DocumentParser.DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES);
        assertTrue(DocumentParser.extractText("a.zip", zipText("0.txt", "x", "1.txt", "y", "2.txt", "z")).contains("[File: 2.txt]"));
        byte[] four = zipText("0.txt", "x", "1.txt", "x", "2.txt", "x", "3.txt", "x");
        ZipLimitException ex = assertThrows(ZipLimitException.class, () -> DocumentParser.extractText("a.zip", four));
        assertEquals("Archive has 4 members (limit 3).", ex.getMessage());
    }

    @Test void directoryEntriesCountAsMembers() throws IOException {
        DocumentParser.setZipLimits(3, DocumentParser.DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES);
        byte[] zip = zipText("d1/", "", "d2/", "", "a.txt", "x", "b.txt", "y");
        ZipLimitException ex = assertThrows(ZipLimitException.class, () -> DocumentParser.extractText("a.zip", zip));
        assertEquals("Archive has 4 members (limit 3).", ex.getMessage());
    }

    @Test void declaredSizeOverTheLimitIsRejectedWithPythonsMessage() throws IOException {
        DocumentParser.setZipLimits(DocumentParser.DEFAULT_MAX_ZIP_MEMBERS, 100);
        byte[] zip = zipText("big.txt", "a".repeat(1000));
        ZipLimitException ex = assertThrows(ZipLimitException.class, () -> DocumentParser.extractText("a.zip", zip));
        assertEquals("Archive declares 1000 bytes uncompressed (limit 100).", ex.getMessage());
    }

    @Test void containerFormatsAreCheckedToo() throws IOException {
        DocumentParser.setZipLimits(DocumentParser.DEFAULT_MAX_ZIP_MEMBERS, 100);
        byte[] zip = zipText("big.txt", "a".repeat(1000));
        for (String name : new String[] {"a.docx", "a.xlsx", "a.pptx", "a.odt", "a.ods", "a.odp", "a.epub"}) {
            assertThrows(ZipLimitException.class, () -> DocumentParser.extractText(name, zip), name);
        }
    }

    @Test void limitErrorsAreIllegalArgumentExceptionsLikePythonsValueError() throws IOException {
        DocumentParser.setZipLimits(1, DocumentParser.DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES);
        byte[] zip = zipText("a.txt", "x", "b.txt", "y");
        assertThrows(IllegalArgumentException.class, () -> DocumentParser.extractText("a.zip", zip));
    }

    @Test void anUnreadableArchiveIsLeftToTheFormatParser() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> DocumentParser.extractText("a.docx", "not a zip".getBytes(StandardCharsets.UTF_8)));
        assertTrue(ex.getMessage().startsWith("Could not read DOCX"));
    }

    @Test void forgedSmallSizesStillHitTheRunningBudget() throws IOException {
        DocumentParser.setZipLimits(DocumentParser.DEFAULT_MAX_ZIP_MEMBERS, 100);
        byte[] forged = forgeUncompressedSize(zipText("big.txt", "a".repeat(5000)), 10);
        ZipLimitException ex = assertThrows(ZipLimitException.class, () -> DocumentParser.extractText("a.zip", forged));
        assertEquals("Archive member data exceeds the 100-byte uncompressed limit.", ex.getMessage());
    }

    @Test void anInnerArchiveOverTheLimitFailsTheWholeZip() throws IOException {
        DocumentParser.setZipLimits(DocumentParser.DEFAULT_MAX_ZIP_MEMBERS, 500);
        Map<String, byte[]> outer = new LinkedHashMap<>();
        outer.put("ok.txt", "fine".getBytes(StandardCharsets.UTF_8));
        outer.put("inner.docx", zipText("big.txt", "a".repeat(1000)));
        byte[] zip = zipBytes(outer);
        ZipLimitException ex = assertThrows(ZipLimitException.class, () -> DocumentParser.extractText("a.zip", zip));
        assertEquals("Archive declares 1000 bytes uncompressed (limit 500).", ex.getMessage());
    }
}
