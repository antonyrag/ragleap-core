package com.ragleap.rag.parsers;

import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** Hand-built minimal packages for the ZIP+XML formats. Exact Python behaviour is covered by PythonParityFixturesTest. */
class OfficeFormatsTest {

    private static final String RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/";
    private static final String PKG_RELS = "xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"";

    private static byte[] zip(String... namesAndContents) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        try (ZipOutputStream z = new ZipOutputStream(bos)) {
            for (int i = 0; i < namesAndContents.length; i += 2) {
                z.putNextEntry(new ZipEntry(namesAndContents[i]));
                z.write(namesAndContents[i + 1].getBytes(StandardCharsets.UTF_8));
                z.closeEntry();
            }
        }
        return bos.toByteArray();
    }

    private static String parse(String filename, byte[] raw) {
        return DocumentParser.extractText(filename, raw);
    }

    // ---------------- DOCX ----------------

    private static byte[] docx(String bodyXml) throws IOException {
        return zip("word/document.xml", "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body>"
                + bodyXml + "</w:body></w:document>");
    }

    @Test void docxMarker() throws IOException {
        assertEquals("ragleapmarker", parse("a.docx", docx("<w:p><w:r><w:t>ragleapmarker</w:t></w:r></w:p>")));
    }

    @Test void docxReadsOnlyBodyLevelParagraphs() throws IOException {
        String body = "<w:p><w:r><w:t>before</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>CELL</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
                + "<w:p><w:r><w:t>after</w:t></w:r></w:p>";
        assertEquals("before\n\nafter", parse("a.docx", docx(body)));
    }

    @Test void docxBreaksTabsAndHyperlinks() throws IOException {
        String body = "<w:p><w:r><w:t>a</w:t><w:br/><w:tab/><w:t>b</w:t></w:r><w:hyperlink><w:r><w:t>L</w:t></w:r></w:hyperlink></w:p>";
        assertEquals("a\n\tbL", parse("a.docx", docx(body)));
    }

    @Test void docxPageBreakAddsNoText() throws IOException {
        assertEquals("ab", parse("a.docx", docx("<w:p><w:r><w:t>a</w:t><w:br w:type=\"page\"/><w:t>b</w:t></w:r></w:p>")));
    }

    @Test void docxWithNoTextIsRejectedWithPythonsMessage() throws IOException {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () -> parse("a.docx", docx("<w:p/>")));
        assertEquals("No text could be extracted from this DOCX file — it may be empty.", ex.getMessage());
    }

    @Test void notAZipIsRejectedForEveryZipBasedFormat() {
        for (String name : new String[] {"a.docx", "a.pptx", "a.xlsx", "a.odt", "a.ods", "a.odp", "a.epub"}) {
            assertThrows(IllegalArgumentException.class, () -> parse(name, "not a zip".getBytes(StandardCharsets.UTF_8)));
        }
    }

    // ---------------- PPTX ----------------

    private static final String PNS = "xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\" "
            + "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" "
            + "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"";

    private static String slide(String text) {
        return "<p:sld " + PNS + "><p:cSld><p:spTree>"
                + (text == null ? "" : "<p:sp><p:txBody><a:p><a:r><a:t>" + text + "</a:t></a:r></a:p></p:txBody></p:sp>")
                + "</p:spTree></p:cSld></p:sld>";
    }

    @Test void pptxSlideNumbersCountEmptySlidesAndNotesAreAppended() throws IOException {
        byte[] raw = zip(
                "ppt/presentation.xml", "<p:presentation " + PNS + "><p:sldIdLst><p:sldId id=\"256\" r:id=\"rId1\"/>"
                        + "<p:sldId id=\"257\" r:id=\"rId2\"/><p:sldId id=\"258\" r:id=\"rId3\"/></p:sldIdLst></p:presentation>",
                "ppt/_rels/presentation.xml.rels", "<Relationships " + PKG_RELS + ">"
                        + "<Relationship Id=\"rId1\" Type=\"" + RT + "slide\" Target=\"slides/slide1.xml\"/>"
                        + "<Relationship Id=\"rId2\" Type=\"" + RT + "slide\" Target=\"slides/slide2.xml\"/>"
                        + "<Relationship Id=\"rId3\" Type=\"" + RT + "slide\" Target=\"slides/slide3.xml\"/></Relationships>",
                "ppt/slides/slide1.xml", slide("ragleapmarker"),
                "ppt/slides/slide2.xml", slide(null),
                "ppt/slides/slide3.xml", slide("third"),
                "ppt/slides/_rels/slide1.xml.rels", "<Relationships " + PKG_RELS + "><Relationship Id=\"rId1\" Type=\"" + RT
                        + "notesSlide\" Target=\"../notesSlides/notesSlide1.xml\"/></Relationships>",
                "ppt/notesSlides/notesSlide1.xml", "<p:notes " + PNS + "><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id=\"1\" name=\"n\"/>"
                        + "<p:cNvSpPr/><p:nvPr><p:ph type=\"body\" idx=\"1\"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>N1</a:t></a:r>"
                        + "<a:br/><a:r><a:t>N2</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>");
        assertEquals("[Slide 1]\nragleapmarker\n[Speaker notes: N1\u000BN2]\n\n[Slide 3]\nthird", parse("a.pptx", raw));
    }

    @Test void pptxWithNoSlidesIsEmptyNotAnError() throws IOException {
        assertEquals("", parse("a.pptx", zip("ppt/presentation.xml", "<p:presentation " + PNS + "/>")));
    }

    // ---------------- XLSX ----------------

    @Test void xlsxValuesSheetsSharedStringsAndDates() throws IOException {
        String m = "xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
                + "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"";
        byte[] raw = zip(
                "xl/workbook.xml", "<workbook " + m + "><sheets><sheet name=\"First\" sheetId=\"1\" r:id=\"rId1\"/>"
                        + "<sheet name=\"Empty\" sheetId=\"2\" r:id=\"rId2\"/></sheets></workbook>",
                "xl/_rels/workbook.xml.rels", "<Relationships " + PKG_RELS + ">"
                        + "<Relationship Id=\"rId1\" Type=\"" + RT + "worksheet\" Target=\"worksheets/sheet1.xml\"/>"
                        + "<Relationship Id=\"rId2\" Type=\"" + RT + "worksheet\" Target=\"worksheets/sheet2.xml\"/>"
                        + "<Relationship Id=\"rId3\" Type=\"" + RT + "sharedStrings\" Target=\"sharedStrings.xml\"/>"
                        + "<Relationship Id=\"rId4\" Type=\"" + RT + "styles\" Target=\"styles.xml\"/></Relationships>",
                "xl/sharedStrings.xml", "<sst " + m + "><si><t>ragleapmarker</t></si></sst>",
                "xl/styles.xml", "<styleSheet " + m + "><cellXfs count=\"2\"><xf numFmtId=\"0\"/><xf numFmtId=\"14\"/></cellXfs></styleSheet>",
                "xl/worksheets/sheet1.xml", "<worksheet " + m + "><sheetData>"
                        + "<row r=\"1\"><c r=\"A1\" t=\"s\"><v>0</v></c><c r=\"B1\"><v>1</v></c><c r=\"C1\"><v>1.5</v></c></row>"
                        + "<row r=\"2\"><c r=\"A2\"/></row>"
                        + "<row r=\"3\"><c r=\"A3\" t=\"b\"><v>1</v></c><c r=\"B3\"><v>1E+25</v></c><c r=\"C3\" s=\"1\"><v>46024</v></c></row>"
                        + "</sheetData></worksheet>",
                "xl/worksheets/sheet2.xml", "<worksheet " + m + "><sheetData/></worksheet>");
        assertEquals("[Sheet: First]\nragleapmarker\t1\t1.5\nTrue\t1e+25\t2026-01-02 00:00:00\n[Sheet: Empty]", parse("a.xlsx", raw));
    }

    // ---------------- ODF ----------------

    private static final String ONS = "xmlns:office=\"urn:oasis:names:tc:opendocument:xmlns:office:1.0\" "
            + "xmlns:text=\"urn:oasis:names:tc:opendocument:xmlns:text:1.0\" "
            + "xmlns:table=\"urn:oasis:names:tc:opendocument:xmlns:table:1.0\"";

    private static byte[] odf(String bodyXml) throws IOException {
        return zip("content.xml", "<office:document-content " + ONS + "><office:body>" + bodyXml + "</office:body></office:document-content>");
    }

    @Test void odtTakesEveryTextPKeepsEmptyOnesAndSkipsHeadings() throws IOException {
        byte[] raw = odf("<office:text><text:h>HEAD</text:h><text:p>one<text:s/>two</text:p><text:p/><text:p>end</text:p></office:text>");
        assertEquals("onetwo\n\nend", parse("a.odt", raw));
        assertEquals("onetwo\n\nend", parse("a.odp", raw));
    }

    @Test void odsJoinsCellsWithTabsAndDropsBlankRows() throws IOException {
        byte[] raw = odf("<office:spreadsheet><table:table>"
                + "<table:table-row><table:table-cell><text:p>a</text:p></table:table-cell><table:table-cell/></table:table-row>"
                + "<table:table-row><table:table-cell/></table:table-row>"
                + "<table:table-row><table:table-cell><text:p>p1</text:p><text:p>p2</text:p></table:table-cell></table:table-row>"
                + "</table:table></office:spreadsheet>");
        assertEquals("a\t\np1p2", parse("a.ods", raw));
    }

    // ---------------- EPUB ----------------

    @Test void epubUsesManifestOrderBodyContentOnlyAndDecodesHrefs() throws IOException {
        byte[] raw = zip(
                "META-INF/container.xml", "<container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\" version=\"1.0\"><rootfiles>"
                        + "<rootfile full-path=\"OEBPS/content.opf\" media-type=\"application/oebps-package+xml\"/></rootfiles></container>",
                "OEBPS/content.opf", "<package xmlns=\"http://www.idpf.org/2007/opf\" version=\"2.0\"><manifest>"
                        + "<item id=\"a\" href=\"a.xhtml\" media-type=\"application/xhtml+xml\"/>"
                        + "<item id=\"b\" href=\"my%20b.xhtml\" media-type=\"application/xhtml+xml\"/>"
                        + "<item id=\"i\" href=\"x.png\" media-type=\"image/png\"/></manifest><spine/></package>",
                "OEBPS/a.xhtml", "<html><head><title>HEADTITLE</title></head><body>LEAD<p>one</p></body></html>",
                "OEBPS/my b.xhtml", "<html><body><p>two</p></body></html>");
        assertEquals("one\n\ntwo", parse("a.epub", raw));
    }

    // ---------------- number and date formatting ----------------

    @Test void pyFloatMatchesPythonRepr() {
        Object[][] cases = {
                {0.1, "0.1"}, {1.0, "1.0"}, {-2.5, "-2.5"}, {1e16, "1e+16"}, {1e15, "1000000000000000.0"},
                {1.5e-7, "1.5e-07"}, {1e-4, "0.0001"}, {1e-5, "1e-05"}, {1e25, "1e+25"},
                {0.1 + 0.2, "0.30000000000000004"}, {123456789.123456789, "123456789.12345679"},
                {12345678901234567890.0, "1.2345678901234567e+19"}, {100.0, "100.0"}
        };
        for (Object[] c : cases) {
            assertEquals(c[1], PyFloat.repr((Double) c[0]), "repr of " + c[0]);
        }
    }

    @Test void excelSerialsFormatLikePythonDatetimes() {
        assertEquals("2026-01-02 00:00:00", ExcelDates.fromExcel(46024.0, false, false));
        assertEquals("2026-01-02 03:04:05", ExcelDates.fromExcel(46024.0 + 11045.0 / 86400.0, false, false));
        assertEquals("12:00:00", ExcelDates.fromExcel(0.5, false, false));
        assertEquals("1 day, 6:00:00", ExcelDates.fromExcel(1.25, false, true));
        assertEquals("1900-02-28 00:00:00", ExcelDates.fromExcel(59.0, false, false));
        assertEquals("1900-03-01 00:00:00", ExcelDates.fromExcel(61.0, false, false));
        assertEquals("1904-01-02 00:00:00", ExcelDates.fromExcel(1.0, true, false));
    }
}
