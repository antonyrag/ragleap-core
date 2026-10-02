package com.ragleap.rag.parsers;

import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;
import org.xml.sax.ErrorHandler;
import org.xml.sax.SAXException;
import org.xml.sax.SAXParseException;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.parsers.ParserConfigurationException;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * A ZIP-based document package (OOXML, ODF, EPUB) opened from bytes. Provides safe
 * XML parsing (no DOCTYPE, no external entities), relationship lookup and a
 * per-part size cap so a small malicious file cannot expand to gigabytes in memory.
 * The bytes are spooled to a temp file so the ZIP central directory is used, which
 * is more robust than streaming and matches Python's zipfile.
 */
final class OpcPackage implements AutoCloseable {

    /** Largest single part (decompressed) that will be loaded. */
    static final long MAX_PART_BYTES = 256L * 1024 * 1024;

    record Rel(String id, String type, String target, boolean external) {
    }

    private final String format;
    private final Path tempFile;
    private final ZipFile zip;

    private OpcPackage(String format, Path tempFile, ZipFile zip) {
        this.format = format;
        this.tempFile = tempFile;
        this.zip = zip;
    }

    static OpcPackage open(byte[] raw, String format) {
        Path tmp = null;
        try {
            tmp = Files.createTempFile("ragleap-", ".zip");
            Files.write(tmp, raw);
            return new OpcPackage(format, tmp, new ZipFile(tmp.toFile()));
        } catch (IOException e) {
            if (tmp != null) {
                try {
                    Files.deleteIfExists(tmp);
                } catch (IOException ignored) {
                    // best effort
                }
            }
            throw new IllegalArgumentException("Could not read " + format + ": " + e.getMessage(), e);
        }
    }

    @Override
    public void close() {
        try {
            zip.close();
        } catch (IOException ignored) {
            // best effort
        }
        try {
            Files.deleteIfExists(tempFile);
        } catch (IOException ignored) {
            // best effort
        }
    }

    /** The part's bytes, or null if there is no such part. */
    byte[] read(String name) {
        ZipEntry entry = zip.getEntry(name);
        if (entry == null) {
            return null;
        }
        try (InputStream in = zip.getInputStream(entry)) {
            byte[] bytes = in.readNBytes((int) (MAX_PART_BYTES + 1));
            if (bytes.length > MAX_PART_BYTES) {
                throw new IllegalArgumentException(format + " part '" + name + "' is larger than the "
                        + (MAX_PART_BYTES / (1024 * 1024)) + " MB safety limit");
            }
            return bytes;
        } catch (IOException e) {
            throw new IllegalArgumentException("Could not read " + format + " part '" + name + "': " + e.getMessage(), e);
        }
    }

    /** The part parsed as XML, or null if there is no such part. */
    Document xml(String name) {
        byte[] bytes = read(name);
        return bytes == null ? null : parseXml(bytes, format, name);
    }

    static Document parseXml(byte[] bytes, String format, String name) {
        try {
            DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
            f.setNamespaceAware(true);
            f.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
            f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
            f.setXIncludeAware(false);
            f.setExpandEntityReferences(false);
            DocumentBuilder b = f.newDocumentBuilder();
            b.setErrorHandler(new ErrorHandler() {
                @Override public void warning(SAXParseException e) { }
                @Override public void error(SAXParseException e) throws SAXException { throw e; }
                @Override public void fatalError(SAXParseException e) throws SAXException { throw e; }
            });
            return b.parse(new ByteArrayInputStream(bytes));
        } catch (ParserConfigurationException | SAXException | IOException e) {
            throw new IllegalArgumentException(
                    "Could not read " + format + ": invalid XML in '" + name + "': " + e.getMessage(), e);
        }
    }

    /** Relationships of a part (use "" for the package-level relationships), keyed by id. */
    Map<String, Rel> rels(String partName) {
        int slash = partName.lastIndexOf('/');
        String dir = slash >= 0 ? partName.substring(0, slash + 1) : "";
        String file = partName.substring(dir.length());
        Map<String, Rel> out = new LinkedHashMap<>();
        Document d = xml(dir + "_rels/" + file + ".rels");
        if (d == null) {
            return out;
        }
        NodeList list = d.getElementsByTagNameNS("*", "Relationship");
        for (int i = 0; i < list.getLength(); i++) {
            Element e = (Element) list.item(i);
            boolean external = "External".equalsIgnoreCase(e.getAttribute("TargetMode"));
            String target = e.getAttribute("Target");
            out.put(e.getAttribute("Id"), new Rel(e.getAttribute("Id"), e.getAttribute("Type"),
                    external ? target : resolve(dir, target), external));
        }
        return out;
    }

    /** Target of the package-level relationship whose type ends with the suffix, else the fallback. */
    String mainPart(String relTypeSuffix, String fallback) {
        for (Rel r : rels("").values()) {
            if (!r.external() && r.type().endsWith("/" + relTypeSuffix)) {
                return r.target();
            }
        }
        return fallback;
    }

    /** Resolves a relationship or manifest target against the directory of the referring part. */
    static String resolve(String baseDir, String target) {
        int hash = target.indexOf('#');
        if (hash >= 0) {
            target = target.substring(0, hash);
        }
        String path = target.startsWith("/") ? target.substring(1) : baseDir + target;
        Deque<String> out = new ArrayDeque<>();
        for (String seg : path.split("/")) {
            if (seg.isEmpty() || seg.equals(".")) {
                continue;
            }
            if (seg.equals("..")) {
                if (!out.isEmpty()) {
                    out.removeLast();
                }
            } else {
                out.addLast(seg);
            }
        }
        return String.join("/", out);
    }

    static List<Element> children(Element parent, String ns, String local) {
        List<Element> out = new ArrayList<>();
        for (Node n = parent.getFirstChild(); n != null; n = n.getNextSibling()) {
            if (n instanceof Element e && ns.equals(e.getNamespaceURI()) && local.equals(e.getLocalName())) {
                out.add(e);
            }
        }
        return out;
    }

    static Element firstChild(Element parent, String ns, String local) {
        List<Element> l = children(parent, ns, local);
        return l.isEmpty() ? null : l.get(0);
    }
}
