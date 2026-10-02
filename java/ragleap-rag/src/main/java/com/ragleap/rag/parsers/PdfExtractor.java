package com.ragleap.rag.parsers;

import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

/**
 * PDF text extraction. Java port of parsers.py's _extract_pdf, using PDFBox in
 * place of pypdf. Same behaviour: pages are joined with a blank line, pages with
 * no extractable text are skipped with a warning, and a PDF with no text at all
 * is rejected. The exact text layout can differ from pypdf's (the two libraries
 * order and space text differently); each page's trailing line break is trimmed.
 */
final class PdfExtractor {

    private static final Logger logger = Logger.getLogger(PdfExtractor.class.getName());

    private PdfExtractor() {
    }

    static String extract(byte[] raw) {
        try (PDDocument doc = Loader.loadPDF(raw)) {
            PDFTextStripper stripper = new PDFTextStripper();
            stripper.setLineSeparator("\n");
            int pageCount = doc.getNumberOfPages();
            List<String> pagesText = new ArrayList<>();
            for (int i = 1; i <= pageCount; i++) {
                stripper.setStartPage(i);
                stripper.setEndPage(i);
                String text = stripper.getText(doc);
                if (!PyText.isBlank(text)) {
                    pagesText.add(text.replaceAll("[\\r\\n]+$", ""));
                } else {
                    logger.warning("No extractable text on PDF page " + i
                            + " (likely scanned/image-only)");
                }
            }
            String fullText = String.join("\n\n", pagesText);
            if (PyText.isBlank(fullText)) {
                throw new IllegalArgumentException(
                        "No text could be extracted from this PDF. It may be a scanned "
                                + "image-only document, which requires OCR (not currently supported).");
            }
            return fullText;
        } catch (IOException e) {
            throw new IllegalArgumentException("Could not read PDF: " + e.getMessage(), e);
        }
    }
}
