package com.ragleap.rag.parsers;

import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

import java.util.ArrayList;
import java.util.List;

/**
 * OpenDocument text extraction. Java port of parsers.py's _extract_odt/_ods/_odp
 * (odfpy). Text and presentations: the text of every text:p element (nested ones
 * included, empty ones kept; headings are not text:p so they are not read), one
 * per line. Spreadsheets: each table row's cells joined by tabs, blank rows dropped.
 * Like odfpy, content.xml and styles.xml are read as one document: body paragraphs
 * first, then master-page headers and footers from styles.xml.
 */
final class OdfExtractor {

    private static final String TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0";
    private static final String TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0";

    private OdfExtractor() {
    }

    private static Document content(OpcPackage pkg, String format) {
        Document d = pkg.xml("content.xml");
        if (d == null) {
            throw new IllegalArgumentException("Could not read " + format + ": 'content.xml' is missing");
        }
        return d;
    }

    static String paragraphs(byte[] raw, String format) {
        try (OpcPackage pkg = OpcPackage.open(raw, format)) {
            List<String> out = new ArrayList<>();
            addParagraphs(content(pkg, format), out);
            Document styles = pkg.xml("styles.xml");
            if (styles != null) {
                addParagraphs(styles, out);
            }
            return String.join("\n", out);
        }
    }

    private static void addParagraphs(Document d, List<String> out) {
        NodeList ps = d.getElementsByTagNameNS(TEXT, "p");
        for (int i = 0; i < ps.getLength(); i++) {
            out.add(ps.item(i).getTextContent());
        }
    }

    static String spreadsheet(byte[] raw) {
        try (OpcPackage pkg = OpcPackage.open(raw, "ODS")) {
            NodeList tables = content(pkg, "ODS").getElementsByTagNameNS(TABLE, "table");
            List<String> out = new ArrayList<>();
            for (int t = 0; t < tables.getLength(); t++) {
                NodeList rows = ((Element) tables.item(t)).getElementsByTagNameNS(TABLE, "table-row");
                for (int r = 0; r < rows.getLength(); r++) {
                    NodeList cells = ((Element) rows.item(r)).getElementsByTagNameNS(TABLE, "table-cell");
                    List<String> texts = new ArrayList<>();
                    for (int c = 0; c < cells.getLength(); c++) {
                        texts.add(cells.item(c).getTextContent());
                    }
                    String rowText = String.join("\t", texts);
                    if (!PyText.isBlank(rowText)) {
                        out.add(rowText);
                    }
                }
            }
            return String.join("\n", out);
        }
    }
}
