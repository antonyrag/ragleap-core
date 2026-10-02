package com.ragleap.rag.parsers;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Expected values were cross-checked against the real BeautifulSoup (html.parser
 * for HTML, lxml-xml for XML), the library Python's parsers.py uses.
 */
class MarkupExtractorTest {

    private static String html(String s) {
        return MarkupExtractor.html(s.getBytes(StandardCharsets.UTF_8));
    }

    private static String xml(String s) {
        return MarkupExtractor.xml(s.getBytes(StandardCharsets.UTF_8));
    }

    @Test void scriptAndStyleAreRemoved() {
        assertEquals("Hello\nWorld", html("<html><head><style>p{color:red}</style>"
                + "<script>var x=1;</script></head><body><p>Hello</p><p> World </p></body></html>"));
    }

    @Test void inlineTagsSplitTextIntoSeparateLines() {
        assertEquals("one\ntwo\nthree", html("<p>one <b>two</b> three</p>"));
    }

    @Test void commentsAreExcluded() {
        assertEquals("a\nb", html("<p>a<!-- hidden -->b</p>"));
    }

    @Test void entitiesAreDecoded() {
        assertEquals("Tom & Jerry <3 \u00e9", html("<p>Tom &amp; Jerry &lt;3 &eacute;</p>"));
    }

    @Test void whitespaceOnlyNodesAreDropped() {
        assertEquals("x", html("<div>\n  <p>x</p>\n</div>"));
    }

    @Test void titleTextIsIncluded() {
        assertEquals("T\nB", html("<html><head><title>T</title></head><body>B</body></html>"));
    }

    @Test void brSplitsText() {
        assertEquals("a\nb", html("<p>a<br>b</p>"));
    }

    @Test void nonBreakingSpaceOnlyNodesAreDropped() {
        assertEquals("x", html("<p>&nbsp;</p><p>x</p>"));
    }

    @Test void unclosedParagraphsStillSplit() {
        assertEquals("one\ntwo", html("<p>one<p>two"));
    }

    @Test void declaredMetaCharsetIsRespected() {
        byte[] raw = "<html><head><meta charset=\"iso-8859-1\"></head><body>caf\u00e9</body></html>"
                .getBytes(StandardCharsets.ISO_8859_1);
        assertEquals("caf\u00e9", MarkupExtractor.html(raw));
    }

    @Test void xmlTextNodesAreJoinedWithNewlines() {
        assertEquals("x\ny", xml("<r><a>x</a><b>y</b></r>"));
    }

    @Test void xmlCdataIsIncludedAndCommentsAreNot() {
        assertEquals("ra<w>", xml("<r><!-- c --><a><![CDATA[ra<w>]]></a></r>"));
    }

    @Test void xmlDeclarationAndNamespacesAreHandled() {
        assertEquals("v", xml("<?xml version=\"1.0\"?><r xmlns:x=\"urn:a\"><x:a>v</x:a></r>"));
    }

    @Test void xmlAttributesAreNotIncluded() {
        assertEquals("v", xml("<r id=\"secret\"><a>v</a></r>"));
    }

    @Test void documentParserDispatchesAllFiveMarkupExtensions() {
        byte[] htmlRaw = "<html><body><p>ragleapmarker</p></body></html>".getBytes(StandardCharsets.UTF_8);
        byte[] xmlRaw = "<r><a>ragleapmarker</a></r>".getBytes(StandardCharsets.UTF_8);
        for (String name : new String[] {"a.html", "a.HTM"}) {
            assertTrue(DocumentParser.extractText(name, htmlRaw).contains("ragleapmarker"));
        }
        for (String name : new String[] {"a.xml", "a.xsl", "a.XSLT"}) {
            assertTrue(DocumentParser.extractText(name, xmlRaw).contains("ragleapmarker"));
        }
    }
}
