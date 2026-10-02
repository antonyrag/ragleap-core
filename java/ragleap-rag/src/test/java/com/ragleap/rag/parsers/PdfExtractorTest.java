package com.ragleap.rag.parsers;

import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Tests build real minimal PDFs by hand, like Python's test_parsers.py does. */
class PdfExtractorTest {

    /** Builds a valid minimal PDF with one page per argument; an empty string gives a blank page. */
    private static byte[] pdf(String... pageTexts) {
        int n = pageTexts.length;
        int fontObj = 3 + 2 * n;
        List<String> objs = new ArrayList<>();
        objs.add("<< /Type /Catalog /Pages 2 0 R >>");
        StringBuilder kids = new StringBuilder();
        for (int i = 0; i < n; i++) {
            kids.append(3 + 2 * i).append(" 0 R ");
        }
        objs.add("<< /Type /Pages /Kids [" + kids + "] /Count " + n + " >>");
        for (int i = 0; i < n; i++) {
            objs.add("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents " + (4 + 2 * i)
                    + " 0 R /Resources << /Font << /F1 " + fontObj + " 0 R >> >> >>");
            String stream = pageTexts[i].isEmpty() ? "" : "BT /F1 12 Tf 10 50 Td (" + pageTexts[i] + ") Tj ET";
            objs.add("<< /Length " + stream.length() + " >>\nstream\n" + stream + "\nendstream");
        }
        objs.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        write(out, "%PDF-1.4\n");
        List<Integer> offsets = new ArrayList<>();
        for (int i = 0; i < objs.size(); i++) {
            offsets.add(out.size());
            write(out, (i + 1) + " 0 obj\n" + objs.get(i) + "\nendobj\n");
        }
        int xref = out.size();
        write(out, "xref\n0 " + (objs.size() + 1) + "\n0000000000 65535 f \n");
        for (int off : offsets) {
            write(out, String.format("%010d 00000 n \n", off));
        }
        write(out, "trailer\n<< /Size " + (objs.size() + 1) + " /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n");
        return out.toByteArray();
    }

    private static void write(ByteArrayOutputStream out, String s) {
        byte[] b = s.getBytes(StandardCharsets.ISO_8859_1);
        out.write(b, 0, b.length);
    }

    @Test void singlePageMarker() {
        assertEquals("ragleapmarker", PdfExtractor.extract(pdf("ragleapmarker")));
    }

    @Test void pagesAreJoinedWithABlankLine() {
        assertEquals("first\n\nsecond", PdfExtractor.extract(pdf("first", "second")));
    }

    @Test void blankPagesAreSkipped() {
        assertEquals("first\n\nthird", PdfExtractor.extract(pdf("first", "", "third")));
    }

    @Test void pdfWithNoTextIsRejected() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> PdfExtractor.extract(pdf("", "")));
        assertTrue(ex.getMessage().contains("No text could be extracted from this PDF"));
    }

    @Test void garbageBytesAreRejectedAsUnreadable() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> PdfExtractor.extract("not a pdf".getBytes(StandardCharsets.UTF_8)));
        assertTrue(ex.getMessage().contains("Could not read PDF"));
    }

    @Test void documentParserDispatchesPdfCaseInsensitively() {
        assertTrue(DocumentParser.extractText("A.PDF", pdf("ragleapmarker")).contains("ragleapmarker"));
    }
}
