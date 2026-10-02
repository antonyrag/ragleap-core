package com.ragleap.rag.parsers;

import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;

import java.util.ArrayList;
import java.util.List;

/**
 * DOCX text extraction. Java port of parsers.py's _extract_docx (python-docx):
 * only the body's own paragraphs are read, so text inside tables, headers and
 * footers is not extracted (same as Python). Paragraph text is built like
 * python-docx: runs and hyperlink runs, with tabs and line breaks translated.
 */
final class DocxExtractor {

    private static final String W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

    private DocxExtractor() {
    }

    static String extract(byte[] raw) {
        try (OpcPackage pkg = OpcPackage.open(raw, "DOCX")) {
            String mainPart = pkg.mainPart("officeDocument", "word/document.xml");
            Document doc = pkg.xml(mainPart);
            if (doc == null) {
                throw new IllegalArgumentException("Could not read DOCX: '" + mainPart + "' is missing");
            }
            Element body = OpcPackage.firstChild(doc.getDocumentElement(), W, "body");
            List<String> paragraphs = new ArrayList<>();
            if (body != null) {
                for (Element p : OpcPackage.children(body, W, "p")) {
                    String text = paragraphText(p);
                    if (!PyText.isBlank(text)) {
                        paragraphs.add(text);
                    }
                }
            }
            String fullText = String.join("\n\n", paragraphs);
            if (PyText.isBlank(fullText)) {
                throw new IllegalArgumentException("No text could be extracted from this DOCX file — it may be empty.");
            }
            return fullText;
        }
    }

    private static String paragraphText(Element p) {
        StringBuilder sb = new StringBuilder();
        for (Node n = p.getFirstChild(); n != null; n = n.getNextSibling()) {
            if (!(n instanceof Element e) || !W.equals(e.getNamespaceURI())) {
                continue;
            }
            if (e.getLocalName().equals("r")) {
                sb.append(runText(e));
            } else if (e.getLocalName().equals("hyperlink")) {
                for (Element r : OpcPackage.children(e, W, "r")) {
                    sb.append(runText(r));
                }
            }
        }
        return sb.toString();
    }

    private static String runText(Element run) {
        StringBuilder sb = new StringBuilder();
        for (Node n = run.getFirstChild(); n != null; n = n.getNextSibling()) {
            if (!(n instanceof Element e) || !W.equals(e.getNamespaceURI())) {
                continue;
            }
            switch (e.getLocalName()) {
                case "t" -> sb.append(e.getTextContent());
                case "tab", "ptab" -> sb.append('\t');
                case "br" -> {
                    String type = e.getAttributeNS(W, "type");
                    if (type.isEmpty() || type.equals("textWrapping")) {
                        sb.append('\n');
                    }
                }
                case "cr" -> sb.append('\n');
                case "noBreakHyphen" -> sb.append('-');
                default -> {
                }
            }
        }
        return sb.toString();
    }
}
