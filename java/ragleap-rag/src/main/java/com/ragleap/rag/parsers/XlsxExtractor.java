package com.ragleap.rag.parsers;

import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;

import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamConstants;
import javax.xml.stream.XMLStreamException;
import javax.xml.stream.XMLStreamReader;
import java.io.ByteArrayInputStream;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * XLSX text extraction. Java port of parsers.py's _extract_xlsx (openpyxl,
 * data_only=True): a "[Sheet: name]" line per worksheet, then each non-blank row as
 * its non-empty cells joined by tabs. Cell values print like Python: integers as
 * integers, floats via repr, booleans as True/False, dates as str(datetime), and a
 * formula with no cached value is skipped. Worksheets are streamed (StAX).
 */
final class XlsxExtractor {

    private static final String M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
    private static final String R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

    private static final Pattern STRIP = Pattern.compile("\\[[^\\]]*\\]|\"[^\"]*\"|\\\\.|_.|\\*.?");
    private static final Pattern DATE_CHARS = Pattern.compile("[dmhysDMHYS]");
    private static final Pattern TIMEDELTA = Pattern.compile(
            "\\[hh?\\](:mm(:ss(\\.0*)?)?)?|\\[mm?\\](:ss(\\.0*)?)?|\\[ss?(\\.0*)?\\]", Pattern.CASE_INSENSITIVE);
    private static final Set<Integer> BUILTIN_DATE = Set.of(14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47);
    private static final Set<Integer> BUILTIN_TIMEDELTA = Set.of(46);

    private record Styles(Set<Integer> date, Set<Integer> timedelta) {
    }

    private XlsxExtractor() {
    }

    static boolean isDateFormat(String fmt) {
        return DATE_CHARS.matcher(STRIP.matcher(fmt.split(";", -1)[0]).replaceAll("")).find();
    }

    static String extract(byte[] raw) {
        try (OpcPackage pkg = OpcPackage.open(raw, "XLSX")) {
            String wbPart = pkg.mainPart("officeDocument", "xl/workbook.xml");
            Document wb = pkg.xml(wbPart);
            if (wb == null) {
                throw new IllegalArgumentException("Could not read XLSX: '" + wbPart + "' is missing");
            }
            Map<String, OpcPackage.Rel> rels = pkg.rels(wbPart);
            Element root = wb.getDocumentElement();
            Element wbPr = OpcPackage.firstChild(root, M, "workbookPr");
            String d1904 = wbPr == null ? "" : wbPr.getAttribute("date1904");
            boolean date1904 = d1904.equals("1") || d1904.equalsIgnoreCase("true");
            List<String> shared = sharedStrings(pkg, rels);
            Styles styles = readStyles(pkg, rels);
            List<String> parts = new ArrayList<>();
            Element sheets = OpcPackage.firstChild(root, M, "sheets");
            if (sheets != null) {
                for (Element sheet : OpcPackage.children(sheets, M, "sheet")) {
                    OpcPackage.Rel rel = rels.get(sheet.getAttributeNS(R, "id"));
                    if (rel == null || rel.external() || !rel.type().endsWith("/worksheet")) {
                        continue;
                    }
                    parts.add("[Sheet: " + sheet.getAttribute("name") + "]");
                    readSheet(pkg, rel.target(), shared, styles, date1904, parts);
                }
            }
            return String.join("\n", parts);
        }
    }

    private static List<String> sharedStrings(OpcPackage pkg, Map<String, OpcPackage.Rel> rels) {
        List<String> out = new ArrayList<>();
        for (OpcPackage.Rel rel : rels.values()) {
            if (rel.external() || !rel.type().endsWith("/sharedStrings")) {
                continue;
            }
            Document d = pkg.xml(rel.target());
            if (d == null) {
                break;
            }
            for (Element si : OpcPackage.children(d.getDocumentElement(), M, "si")) {
                StringBuilder sb = new StringBuilder();
                for (Node n = si.getFirstChild(); n != null; n = n.getNextSibling()) {
                    if (!(n instanceof Element e) || !M.equals(e.getNamespaceURI())) {
                        continue;
                    }
                    if (e.getLocalName().equals("t")) {
                        sb.append(e.getTextContent());
                    } else if (e.getLocalName().equals("r")) {
                        for (Element t : OpcPackage.children(e, M, "t")) {
                            sb.append(t.getTextContent());
                        }
                    }
                }
                out.add(sb.toString());
            }
            break;
        }
        return out;
    }

    private static Styles readStyles(OpcPackage pkg, Map<String, OpcPackage.Rel> rels) {
        Set<Integer> date = new HashSet<>();
        Set<Integer> td = new HashSet<>();
        for (OpcPackage.Rel rel : rels.values()) {
            if (rel.external() || !rel.type().endsWith("/styles")) {
                continue;
            }
            Document d = pkg.xml(rel.target());
            if (d == null) {
                break;
            }
            Element root = d.getDocumentElement();
            Map<Integer, String> custom = new HashMap<>();
            Element numFmts = OpcPackage.firstChild(root, M, "numFmts");
            if (numFmts != null) {
                for (Element nf : OpcPackage.children(numFmts, M, "numFmt")) {
                    custom.put(Integer.parseInt(nf.getAttribute("numFmtId")), nf.getAttribute("formatCode"));
                }
            }
            Element xfs = OpcPackage.firstChild(root, M, "cellXfs");
            if (xfs != null) {
                int idx = 0;
                for (Element xf : OpcPackage.children(xfs, M, "xf")) {
                    String idAttr = xf.getAttribute("numFmtId");
                    int id = idAttr.isEmpty() ? 0 : Integer.parseInt(idAttr);
                    String code = custom.get(id);
                    boolean isDate = code != null ? isDateFormat(code) : BUILTIN_DATE.contains(id);
                    boolean isTd = code != null ? TIMEDELTA.matcher(code.split(";", -1)[0]).find()
                            : BUILTIN_TIMEDELTA.contains(id);
                    if (isDate) {
                        date.add(idx);
                    }
                    if (isTd) {
                        td.add(idx);
                    }
                    idx++;
                }
            }
            break;
        }
        return new Styles(date, td);
    }

    private static void readSheet(OpcPackage pkg, String part, List<String> shared, Styles styles,
                                  boolean date1904, List<String> out) {
        byte[] bytes = pkg.read(part);
        if (bytes == null) {
            return;
        }
        XMLInputFactory f = XMLInputFactory.newFactory();
        f.setProperty(XMLInputFactory.SUPPORT_DTD, false);
        f.setProperty(XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES, false);
        try {
            XMLStreamReader r = f.createXMLStreamReader(new ByteArrayInputStream(bytes));
            List<String> row = null;
            while (r.hasNext()) {
                int ev = r.next();
                if (ev == XMLStreamConstants.START_ELEMENT) {
                    String n = r.getLocalName();
                    if (n.equals("row")) {
                        row = new ArrayList<>();
                    } else if (n.equals("c") && row != null) {
                        String v = readCell(r, shared, styles, date1904);
                        if (v != null) {
                            row.add(v);
                        }
                    }
                } else if (ev == XMLStreamConstants.END_ELEMENT && r.getLocalName().equals("row") && row != null) {
                    String text = String.join("\t", row);
                    if (!PyText.isBlank(text)) {
                        out.add(text);
                    }
                    row = null;
                }
            }
        } catch (XMLStreamException e) {
            throw new IllegalArgumentException("Could not read XLSX worksheet '" + part + "': " + e.getMessage(), e);
        }
    }

    private static String readCell(XMLStreamReader r, List<String> shared, Styles st, boolean date1904)
            throws XMLStreamException {
        String type = r.getAttributeValue(null, "t");
        String sAttr = r.getAttributeValue(null, "s");
        int style = sAttr == null || sAttr.isBlank() ? 0 : Integer.parseInt(sAttr.trim());
        String v = null;
        String inline = null;
        while (r.hasNext()) {
            int ev = r.next();
            if (ev == XMLStreamConstants.START_ELEMENT) {
                String n = r.getLocalName();
                if (n.equals("v")) {
                    String text = r.getElementText();
                    if (v == null) {
                        v = text;
                    }
                } else if (n.equals("is")) {
                    inline = richText(r);
                }
            } else if (ev == XMLStreamConstants.END_ELEMENT && r.getLocalName().equals("c")) {
                break;
            }
        }
        if (v != null && v.isEmpty()) {
            v = null;
        }
        return switch (type == null ? "n" : type) {
            case "inlineStr" -> inline;
            case "s" -> {
                if (v == null) {
                    yield null;
                }
                int idx = Integer.parseInt(v.trim());
                yield idx >= 0 && idx < shared.size() ? shared.get(idx) : null;
            }
            case "b" -> v == null ? null : (Integer.parseInt(v.trim()) != 0 ? "True" : "False");
            case "str", "e" -> v;
            case "d" -> v == null ? null : v.replace('T', ' ');
            default -> v == null ? null : numeric(v, style, st, date1904);
        };
    }

    private static String richText(XMLStreamReader r) throws XMLStreamException {
        StringBuilder sb = new StringBuilder();
        int depth = 1;
        int phonetic = 0;
        while (depth > 0 && r.hasNext()) {
            int ev = r.next();
            if (ev == XMLStreamConstants.START_ELEMENT) {
                String n = r.getLocalName();
                if (n.equals("rPh")) {
                    phonetic++;
                    depth++;
                } else if (n.equals("t") && phonetic == 0) {
                    sb.append(r.getElementText());
                } else {
                    depth++;
                }
            } else if (ev == XMLStreamConstants.END_ELEMENT) {
                if (r.getLocalName().equals("rPh")) {
                    phonetic--;
                }
                depth--;
            }
        }
        return sb.toString();
    }

    private static String numeric(String v, int style, Styles st, boolean date1904) {
        String t = v.trim();
        boolean isFloat = t.contains(".") || t.contains("E") || t.contains("e");
        double asDouble;
        BigInteger asInt = null;
        try {
            if (isFloat) {
                asDouble = Double.parseDouble(t);
            } else {
                asInt = new BigInteger(t);
                asDouble = asInt.doubleValue();
            }
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("Invalid numeric cell value '" + v + "' in XLSX worksheet");
        }
        if (st.date().contains(style)) {
            String s = ExcelDates.fromExcel(asDouble, date1904, st.timedelta().contains(style));
            return s != null ? s : "#VALUE!";
        }
        return isFloat ? PyFloat.repr(asDouble) : asInt.toString();
    }
}
