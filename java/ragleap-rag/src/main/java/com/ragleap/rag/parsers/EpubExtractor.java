package com.ragleap.rag.parsers;

import org.jsoup.Jsoup;
import org.jsoup.nodes.TextNode;
import org.jsoup.parser.Parser;
import org.jsoup.select.NodeTraversor;
import org.jsoup.select.NodeVisitor;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * EPUB text extraction. Java port of parsers.py's _extract_epub (ebooklib).
 * Documents are taken in manifest order (not reading order), nav document included.
 * Like ebooklib's get_content(), only the body's content is used: the head (title,
 * styles) and any text sitting directly in the body before its first child element
 * are not extracted. Documents are joined with a blank line.
 */
final class EpubExtractor {

    private static final String CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container";
    private static final String OPF = "http://www.idpf.org/2007/opf";

    private EpubExtractor() {
    }

    static String extract(byte[] raw) {
        try (OpcPackage pkg = OpcPackage.open(raw, "EPUB")) {
            Document container = pkg.xml("META-INF/container.xml");
            if (container == null) {
                throw new IllegalArgumentException("Could not read EPUB: META-INF/container.xml is missing");
            }
            NodeList rootfiles = container.getElementsByTagNameNS(CONTAINER, "rootfile");
            if (rootfiles.getLength() == 0) {
                throw new IllegalArgumentException("Could not read EPUB: no rootfile in container.xml");
            }
            String opfPath = ((Element) rootfiles.item(0)).getAttribute("full-path");
            Document opf = pkg.xml(opfPath);
            if (opf == null) {
                throw new IllegalArgumentException("Could not read EPUB: package file '" + opfPath + "' is missing");
            }
            String dir = opfPath.contains("/") ? opfPath.substring(0, opfPath.lastIndexOf('/') + 1) : "";
            Element manifest = OpcPackage.firstChild(opf.getDocumentElement(), OPF, "manifest");
            List<String> parts = new ArrayList<>();
            if (manifest != null) {
                for (Element item : OpcPackage.children(manifest, OPF, "item")) {
                    String name = OpcPackage.resolve(dir, decode(item.getAttribute("href")));
                    String mediaType = item.getAttribute("media-type");
                    String text;
                    if (mediaType.equals("application/xhtml+xml")) {
                        byte[] bytes = pkg.read(name);
                        if (bytes == null) {
                            continue;
                        }
                        text = bodyText(bytes);
                    } else if (hasDocumentExtension(name)) {
                        byte[] bytes = pkg.read(name);
                        if (bytes == null) {
                            continue;
                        }
                        text = MarkupExtractor.html(bytes);
                    } else {
                        continue;
                    }
                    if (!PyText.isBlank(text)) {
                        parts.add(text);
                    }
                }
            }
            return String.join("\n\n", parts);
        }
    }

    private static boolean hasDocumentExtension(String name) {
        String lower = name.toLowerCase(Locale.ROOT);
        return lower.endsWith(".html") || lower.endsWith(".xhtml") || lower.endsWith(".htm");
    }

    private static String decode(String href) {
        return URLDecoder.decode(href.replace("+", "%2B"), StandardCharsets.UTF_8);
    }

    private static String bodyText(byte[] bytes) {
        org.jsoup.nodes.Document doc;
        try {
            doc = Jsoup.parse(new ByteArrayInputStream(bytes), null, "", Parser.htmlParser());
        } catch (IOException e) {
            throw new IllegalArgumentException("Could not parse EPUB document: " + e.getMessage(), e);
        }
        doc.select("script, style").remove();
        List<String> parts = new ArrayList<>();
        NodeVisitor visitor = new NodeVisitor() {
            @Override
            public void head(org.jsoup.nodes.Node node, int depth) {
                if (node instanceof TextNode t) {
                    String stripped = PyText.strip(t.getWholeText());
                    if (!stripped.isEmpty()) {
                        parts.add(stripped);
                    }
                }
            }

            @Override
            public void tail(org.jsoup.nodes.Node node, int depth) {
            }
        };
        boolean leading = true;
        for (org.jsoup.nodes.Node n : new ArrayList<>(doc.body().childNodes())) {
            if (leading && n instanceof TextNode) {
                continue;
            }
            leading = false;
            NodeTraversor.traverse(visitor, n);
        }
        return String.join("\n", parts);
    }
}
