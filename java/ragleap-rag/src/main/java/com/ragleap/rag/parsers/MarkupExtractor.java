package com.ragleap.rag.parsers;

import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Node;
import org.jsoup.nodes.TextNode;
import org.jsoup.parser.Parser;
import org.jsoup.select.NodeTraversor;
import org.jsoup.select.NodeVisitor;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * HTML and XML text extraction. Java port of parsers.py's _extract_html and
 * _extract_xml, which use BeautifulSoup get_text(separator="\n", strip=True):
 * every text node is stripped, empty ones are dropped, the rest are joined with
 * newlines. Comments and the doctype are not text nodes. For HTML, script and
 * style elements are removed first; the XML path does not do that (same as Python).
 *
 * <p>Known differences from BeautifulSoup's html.parser: jsoup follows the HTML5
 * tree-building rules, so text placed directly inside a table outside any cell is
 * moved before the table, and with no declared charset and invalid UTF-8 jsoup
 * assumes UTF-8 where BeautifulSoup falls back to windows-1252.
 */
final class MarkupExtractor {

    private MarkupExtractor() {
    }

    static String html(byte[] raw) {
        Document doc = parse(raw, Parser.htmlParser());
        doc.select("script, style").remove();
        return joinStrippedText(doc);
    }

    static String xml(byte[] raw) {
        return joinStrippedText(parse(raw, Parser.xmlParser()));
    }

    private static Document parse(byte[] raw, Parser parser) {
        try {
            return Jsoup.parse(new ByteArrayInputStream(raw), null, "", parser);
        } catch (IOException e) {
            throw new IllegalArgumentException("Could not parse markup: " + e.getMessage(), e);
        }
    }

    private static String joinStrippedText(Document doc) {
        List<String> parts = new ArrayList<>();
        NodeTraversor.traverse(new NodeVisitor() {
            @Override
            public void head(Node node, int depth) {
                if (node instanceof TextNode textNode) {
                    String stripped = PyText.strip(textNode.getWholeText());
                    if (!stripped.isEmpty()) {
                        parts.add(stripped);
                    }
                }
            }

            @Override
            public void tail(Node node, int depth) {
            }
        }, doc);
        return String.join("\n", parts);
    }
}
