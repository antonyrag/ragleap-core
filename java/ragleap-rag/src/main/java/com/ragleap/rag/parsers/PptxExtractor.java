package com.ragleap.rag.parsers;

import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * PPTX text extraction. Java port of parsers.py's _extract_pptx (python-pptx).
 * Slides follow the presentation's slide list; a slide's number counts even if it
 * has no text. Only text in plain shapes and placeholders is read (group shapes,
 * tables and pictures are skipped, same as Python). Speaker notes are appended.
 */
final class PptxExtractor {

    private static final String A = "http://schemas.openxmlformats.org/drawingml/2006/main";
    private static final String P = "http://schemas.openxmlformats.org/presentationml/2006/main";
    private static final String R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

    private PptxExtractor() {
    }

    static String extract(byte[] raw) {
        try (OpcPackage pkg = OpcPackage.open(raw, "PPTX")) {
            String presPart = pkg.mainPart("officeDocument", "ppt/presentation.xml");
            Document pres = pkg.xml(presPart);
            if (pres == null) {
                throw new IllegalArgumentException("Could not read PPTX: '" + presPart + "' is missing");
            }
            Map<String, OpcPackage.Rel> rels = pkg.rels(presPart);
            Element idList = OpcPackage.firstChild(pres.getDocumentElement(), P, "sldIdLst");
            List<String> parts = new ArrayList<>();
            if (idList != null) {
                int number = 0;
                for (Element sldId : OpcPackage.children(idList, P, "sldId")) {
                    number++;
                    OpcPackage.Rel rel = rels.get(sldId.getAttributeNS(R, "id"));
                    if (rel == null || rel.external()) {
                        continue;
                    }
                    String text = slideText(pkg, rel.target());
                    if (text != null) {
                        parts.add("[Slide " + number + "]\n" + text);
                    }
                }
            }
            return String.join("\n\n", parts);
        }
    }

    private static Element shapeTree(Document d) {
        Element cSld = OpcPackage.firstChild(d.getDocumentElement(), P, "cSld");
        return cSld == null ? null : OpcPackage.firstChild(cSld, P, "spTree");
    }

    private static String slideText(OpcPackage pkg, String slidePart) {
        Document slide = pkg.xml(slidePart);
        if (slide == null) {
            return null;
        }
        List<String> lines = new ArrayList<>();
        Element tree = shapeTree(slide);
        if (tree != null) {
            for (Element sp : OpcPackage.children(tree, P, "sp")) {
                Element tx = OpcPackage.firstChild(sp, P, "txBody");
                if (tx == null) {
                    continue;
                }
                for (Element para : OpcPackage.children(tx, A, "p")) {
                    StringBuilder sb = new StringBuilder();
                    for (Element run : OpcPackage.children(para, A, "r")) {
                        Element t = OpcPackage.firstChild(run, A, "t");
                        if (t != null) {
                            sb.append(t.getTextContent());
                        }
                    }
                    if (!PyText.isBlank(sb.toString())) {
                        lines.add(sb.toString());
                    }
                }
            }
        }
        String notes = notesText(pkg, slidePart);
        if (notes != null && !PyText.isBlank(notes)) {
            lines.add("[Speaker notes: " + notes + "]");
        }
        return lines.isEmpty() ? null : String.join("\n", lines);
    }

    /** Text of the notes slide's body placeholder, paragraphs joined by newline (python-pptx text_frame.text). */
    private static String notesText(OpcPackage pkg, String slidePart) {
        for (OpcPackage.Rel rel : pkg.rels(slidePart).values()) {
            if (rel.external() || !rel.type().endsWith("/notesSlide")) {
                continue;
            }
            Document notes = pkg.xml(rel.target());
            Element tree = notes == null ? null : shapeTree(notes);
            if (tree == null) {
                return null;
            }
            for (Element sp : OpcPackage.children(tree, P, "sp")) {
                Element nvSpPr = OpcPackage.firstChild(sp, P, "nvSpPr");
                Element nvPr = nvSpPr == null ? null : OpcPackage.firstChild(nvSpPr, P, "nvPr");
                Element ph = nvPr == null ? null : OpcPackage.firstChild(nvPr, P, "ph");
                if (ph == null || !"body".equals(ph.getAttribute("type"))) {
                    continue;
                }
                Element tx = OpcPackage.firstChild(sp, P, "txBody");
                List<String> paras = new ArrayList<>();
                if (tx != null) {
                    for (Element para : OpcPackage.children(tx, A, "p")) {
                        StringBuilder sb = new StringBuilder();
                        for (Node n = para.getFirstChild(); n != null; n = n.getNextSibling()) {
                            if (!(n instanceof Element e) || !A.equals(e.getNamespaceURI())) {
                                continue;
                            }
                            switch (e.getLocalName()) {
                                case "r", "fld" -> {
                                    Element t = OpcPackage.firstChild(e, A, "t");
                                    if (t != null) {
                                        sb.append(t.getTextContent());
                                    }
                                }
                                case "br" -> sb.append('\u000B');
                                default -> {
                                }
                            }
                        }
                        paras.add(sb.toString());
                    }
                }
                return String.join("\n", paras);
            }
            return null;
        }
        return null;
    }
}
