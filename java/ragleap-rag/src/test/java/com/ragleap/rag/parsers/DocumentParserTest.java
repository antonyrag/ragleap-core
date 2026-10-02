package com.ragleap.rag.parsers;

import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Tests for DocumentParser, mirroring the marker-per-extension approach of Python's test_parsers.py. */
class DocumentParserTest {

    private static final String MARKER = "ragleapmarker";

    private static String parse(String filename, String content) {
        return DocumentParser.extractText(filename, content.getBytes(StandardCharsets.UTF_8));
    }

    private static byte[] zip(Map<String, String> entries) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        try (ZipOutputStream zos = new ZipOutputStream(bos)) {
            for (Map.Entry<String, String> e : entries.entrySet()) {
                zos.putNextEntry(new ZipEntry(e.getKey()));
                zos.write(e.getValue().getBytes(StandardCharsets.UTF_8));
                zos.closeEntry();
            }
        }
        return bos.toByteArray();
    }

    // ---- one marker test per implemented extension ----

    @Test void txtMarker() { assertTrue(parse("a.txt", "hello " + MARKER).contains(MARKER)); }
    @Test void mdMarker() { assertTrue(parse("a.md", "# t\n" + MARKER).contains(MARKER)); }
    @Test void sqlMarker() { assertTrue(parse("a.sql", "-- " + MARKER + "\nSELECT 1;").contains(MARKER)); }
    @Test void csvMarker() { assertTrue(parse("a.csv", "a,b\n" + MARKER + ",2\n").contains(MARKER)); }
    @Test void tsvMarker() { assertTrue(parse("a.tsv", "a\tb\n" + MARKER + "\t2\n").contains(MARKER)); }
    @Test void jsonMarker() { assertTrue(parse("a.json", "{\"k\": \"" + MARKER + "\"}").contains(MARKER)); }
    @Test void yamlMarker() { assertTrue(parse("a.yaml", "key: " + MARKER + "\n").contains(MARKER)); }
    @Test void ymlMarker() { assertTrue(parse("a.yml", "key: " + MARKER + "\n").contains(MARKER)); }
    @Test void vttMarker() {
        assertTrue(parse("a.vtt", "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n" + MARKER + "\n").contains(MARKER));
    }
    @Test void srtMarker() {
        assertTrue(parse("a.srt", "1\n00:00:01,000 --> 00:00:02,000\n" + MARKER + "\n").contains(MARKER));
    }
    @Test void zipMarker() throws IOException {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("in.txt", MARKER);
        assertTrue(DocumentParser.extractText("a.zip", zip(m)).contains(MARKER));
    }

    // ---- dispatch and errors ----

    @Test void extensionIsCaseInsensitive() {
        assertTrue(parse("NOTES.TXT", MARKER).contains(MARKER));
    }

    @Test void legacyOfficeFormatsAreRejectedWithConversionHint() {
        for (String name : new String[] {"old.doc", "old.ppt"}) {
            IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () -> parse(name, "x"));
            assertTrue(ex.getMessage().contains("legacy binary Office format"));
        }
    }

    @Test void unknownExtensionIsRejected() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () -> parse("a.exe", "x"));
        assertTrue(ex.getMessage().contains("Unsupported file type '.exe'"));
    }

    @Test void filenameWithoutExtensionIsRejected() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () -> parse("README", "x"));
        assertTrue(ex.getMessage().contains("Unsupported file type '.'"));
    }

    @Test void parquetIsDeliberatelyDeferred() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () -> parse("a.parquet", "x"));
        assertTrue(ex.getMessage().contains("Parquet"));
    }

    // ---- text decoding ----

    @Test void utf8IsDecodedAsUtf8() {
        assertEquals("héllo", parse("a.txt", "héllo"));
    }

    @Test void invalidUtf8FallsBackToLatin1() {
        byte[] raw = {'h', (byte) 0xE9, 'l'};
        assertEquals("h\u00E9l", DocumentParser.extractText("a.txt", raw));
    }

    // ---- csv / tsv ----

    @Test void csvQuotedFieldWithDelimiterAndEmbeddedNewline() {
        assertEquals("a\tb,c\nline1\nline2\td", parse("a.csv", "a,\"b,c\"\n\"line1\nline2\",d\n"));
    }

    @Test void csvDoubledQuoteIsAnEscapedQuote() {
        assertEquals("say \"hi\"\tx", parse("a.csv", "\"say \"\"hi\"\"\",x\n"));
    }

    @Test void csvBlankLineIsKeptAsEmptyRow() {
        assertEquals("a\tb\n\nc\td", parse("a.csv", "a,b\n\nc,d\n"));
    }

    @Test void csvHandlesCrlf() {
        assertEquals("a\tb\nc\td", parse("a.csv", "a,b\r\nc,d\r\n"));
    }

    @Test void csvKeepsEmptyTrailingField() {
        assertEquals("a\t", parse("a.csv", "a,\n"));
    }

    @Test void tsvKeepsQuotesLiteralWhenNotAtFieldStart() {
        assertEquals("a\tb\"c\td", parse("a.tsv", "a\tb\"c\td\n"));
    }

    // ---- json / yaml ----

    @Test void jsonIsPrettyPrintedLikePythonIndent2() {
        String input = "{\"k\":\"v\",\"n\":[1,2],\"e\":{},\"l\":[],\"o\":{\"x\":null,\"t\":true}}";
        String expected = "{\n"
                + "  \"k\": \"v\",\n"
                + "  \"n\": [\n"
                + "    1,\n"
                + "    2\n"
                + "  ],\n"
                + "  \"e\": {},\n"
                + "  \"l\": [],\n"
                + "  \"o\": {\n"
                + "    \"x\": null,\n"
                + "    \"t\": true\n"
                + "  }\n"
                + "}";
        assertEquals(expected, parse("a.json", input));
    }

    @Test void jsonNonAsciiIsNotEscaped() {
        assertTrue(parse("a.json", "{\"n\":\"é日本\"}").contains("é日本"));
    }

    @Test void invalidJsonIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> parse("a.json", "{not json"));
    }

    @Test void jsonWithTrailingDataIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> parse("a.json", "{\"a\":1} {\"b\":2}"));
    }

    @Test void emptyJsonIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> parse("a.json", ""));
    }

    @Test void yamlIsDumpedAsIndentedJson() {
        String expected = "{\n  \"a\": 1,\n  \"b\": [\n    \"x\",\n    \"y\"\n  ]\n}";
        assertEquals(expected, parse("a.yaml", "a: 1\nb:\n  - x\n  - y\n"));
    }

    @Test void emptyYamlIsNull() {
        assertEquals("null", parse("a.yaml", ""));
    }

    // ---- subtitles ----

    @Test void vttStripsHeaderTimestampsAndCueNumbers() {
        String vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n\n2\n00:00:03.000 --> 00:00:04.000\nworld\n";
        assertEquals("hello\nworld", parse("a.vtt", vtt));
    }

    @Test void srtStripsTimestampsAndCueNumbers() {
        String srt = "1\n00:00:01,000 --> 00:00:02,000\nhi\n\n2\n00:00:03,000 --> 00:00:04,000\nthere\n";
        assertEquals("hi\nthere", parse("a.srt", srt));
    }

    // ---- zip ----

    @Test void zipLabelsEachFile() throws IOException {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("a.txt", "first");
        m.put("sub/b.md", "second");
        assertEquals("[File: a.txt]\nfirst\n\n[File: sub/b.md]\nsecond",
                DocumentParser.extractText("x.zip", zip(m)));
    }

    @Test void zipSkipsDirectoriesUnsupportedTypesAndNestedZips() throws IOException {
        Map<String, String> inner = new LinkedHashMap<>();
        inner.put("deep.txt", "deep");
        Map<String, String> m = new LinkedHashMap<>();
        m.put("dir/", "");
        m.put("image.bin", "binary");
        m.put("nested.zip", new String(zip(inner), StandardCharsets.ISO_8859_1));
        m.put("keep.txt", "kept");
        String out = DocumentParser.extractText("x.zip", zip(m));
        assertEquals("[File: keep.txt]\nkept", out);
    }

    @Test void zipSkipsFilesThatFailExtractionButKeepsTheRest() throws IOException {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("bad.json", "{not json");
        m.put("good.txt", "good");
        assertEquals("[File: good.txt]\ngood", DocumentParser.extractText("x.zip", zip(m)));
    }

    @Test void zipWithNothingExtractableIsRejected() throws IOException {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("image.bin", "binary");
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> DocumentParser.extractText("x.zip", zip(m)));
        assertTrue(ex.getMessage().contains("No extractable text"));
    }
}
