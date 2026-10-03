package com.ragleap.rag.parsers;

import java.io.ByteArrayOutputStream;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * .eml text extraction. Java port of parsers.py's _extract_eml, which uses Python's email
 * package with policy.default. Output is "From: ...", "To: ...", "Subject: ..." followed by
 * the body, joined by newlines. This is a small dedicated parser (no mail library) so that
 * Python's specific behaviours can be reproduced:
 * <ul>
 *   <li>the body is the first text/plain part (else the first text/html, converted to text),
 *       skipping attachments, searched through multipart/* and multipart/related;</li>
 *   <li>a body part with no headers at all is treated as missing (Python tests the message
 *       object's truthiness, and an email object with no headers is false);</li>
 *   <li>the body is decoded with its declared charset, default ASCII with replacement
 *       characters; an unknown charset is an error;</li>
 *   <li>address headers are re-rendered like Python (display name quoted if it contains
 *       specials, comments dropped, addresses joined by ", ") by a simplified address parser;
 *       unusual forms (obsolete syntax, routes) may differ.</li>
 * </ul>
 * Nesting deeper than {@value #MAX_DEPTH} multipart levels is not followed (hardening).
 */
final class EmlExtractor {

    private static final int MAX_DEPTH = 32;
    private static final String SPECIALS = "()<>@,:;.\\\"[]";
    private static final Pattern ENCODED_WORD = Pattern.compile("=\\?([^?\\s]+)\\?([bBqQ])\\?([^?\\s]*)\\?=");

    private record Header(String name, String value) {
    }

    /** One message or MIME part. The text is the whole message with one char per byte. */
    private static final class Entity {
        final String text;
        final List<Header> headers = new ArrayList<>();
        int bodyStart;
        int bodyEnd;
        List<Entity> parts;

        Entity(String text) {
            this.text = text;
        }

        String header(String name) {
            for (Header h : headers) {
                if (h.name().equalsIgnoreCase(name)) {
                    return h.value();
                }
            }
            return null;
        }
    }

    private EmlExtractor() {
    }

    static String extract(byte[] raw) {
        String text = new String(raw, StandardCharsets.ISO_8859_1);
        Entity msg = parse(text, 0, text.length(), 0);
        List<String> out = new ArrayList<>();
        out.add("From: " + addressHeader(msg.header("from")));
        out.add("To: " + addressHeader(msg.header("to")));
        out.add("Subject: " + unstructured(msg.header("subject")));
        Entity[] best = new Entity[2];
        collect(msg, msg, best);
        Entity body = best[0] != null ? best[0] : best[1];
        if (body != null && !body.headers.isEmpty()) {
            String content = textContent(body);
            if (contentType(body).equals("text/html")) {
                content = MarkupExtractor.html(content.getBytes(StandardCharsets.UTF_8));
            }
            out.add(content);
        }
        return String.join("\n", out);
    }

    // ------------------------------------------------------------------ parsing

    private static Entity parse(String text, int start, int end, int depth) {
        Entity e = new Entity(text);
        int pos = start;
        boolean first = true;
        String curName = null;
        StringBuilder curValue = null;
        while (pos < end) {
            int eol = lineEnd(text, pos, end);
            int next = nextLine(text, eol, end);
            String line = text.substring(pos, eol);
            if (line.isEmpty() && next > eol) {
                pos = next;
                break;
            }
            if (first && line.startsWith("From ")) {
                first = false;
                pos = next;
                continue;
            }
            first = false;
            if (line.startsWith(" ") || line.startsWith("\t")) {
                if (curValue != null) {
                    curValue.append(line);
                }
                pos = next;
                continue;
            }
            int colon = line.indexOf(':');
            if (colon > 0 && validHeaderName(line, colon)) {
                if (curName != null) {
                    e.headers.add(new Header(curName, curValue.toString()));
                }
                curName = line.substring(0, colon);
                curValue = new StringBuilder(lstrip(line.substring(colon + 1)));
                pos = next;
                continue;
            }
            break;
        }
        if (curName != null) {
            e.headers.add(new Header(curName, curValue.toString()));
        }
        e.bodyStart = pos;
        e.bodyEnd = end;
        if (depth < MAX_DEPTH && contentType(e).startsWith("multipart/")) {
            String boundary = param(e.header("content-type"), "boundary");
            if (boundary != null && !boundary.isEmpty()) {
                e.parts = splitParts(e, boundary.stripTrailing(), depth);
            }
        }
        return e;
    }

    private static int lineEnd(String text, int pos, int end) {
        int i = pos;
        while (i < end && text.charAt(i) != '\r' && text.charAt(i) != '\n') {
            i++;
        }
        return i;
    }

    private static int nextLine(String text, int eol, int end) {
        if (eol >= end) {
            return eol;
        }
        if (text.charAt(eol) == '\r' && eol + 1 < end && text.charAt(eol + 1) == '\n') {
            return eol + 2;
        }
        return eol + 1;
    }

    private static boolean validHeaderName(String line, int colon) {
        for (int i = 0; i < colon; i++) {
            char c = line.charAt(i);
            if (c < 0x21 || c > 0x7E) {
                return false;
            }
        }
        return true;
    }

    private static String lstrip(String s) {
        int i = 0;
        while (i < s.length() && (s.charAt(i) == ' ' || s.charAt(i) == '\t')) {
            i++;
        }
        return s.substring(i);
    }

    /** Splits a multipart body at its boundary lines; null if no opening boundary line exists. */
    private static List<Entity> splitParts(Entity e, String boundary, int depth) {
        String text = e.text;
        String delim = "--" + boundary;
        List<Entity> parts = new ArrayList<>();
        int pos = e.bodyStart;
        int end = e.bodyEnd;
        boolean inPart = false;
        boolean sawStart = false;
        int partStart = 0;
        int prevEolLen = 0;
        while (pos < end) {
            int eol = lineEnd(text, pos, end);
            int next = nextLine(text, eol, end);
            int kind = matchDelimiter(text, pos, eol, delim);
            if (kind != 0) {
                if (inPart) {
                    int partEnd = Math.max(partStart, pos - prevEolLen);
                    parts.add(parse(text, partStart, partEnd, depth + 1));
                }
                sawStart = true;
                if (kind == 2) {
                    inPart = false;
                    break;
                }
                inPart = true;
                partStart = next;
            }
            prevEolLen = next - eol;
            pos = next;
        }
        if (inPart) {
            Entity last = parse(text, partStart, end, depth + 1);
            // Python's feedparser strips one trailing line break from the last part of an
            // unterminated multipart (only when that part is a leaf, not another multipart).
            if (last.parts == null && last.bodyEnd > last.bodyStart) {
                last.bodyEnd -= trailingEolLength(text, last.bodyStart, last.bodyEnd);
            }
            parts.add(last);
        }
        return sawStart ? parts : null;
    }

    private static int trailingEolLength(String text, int start, int end) {
        if (text.charAt(end - 1) == '\n') {
            return end - 2 >= start && text.charAt(end - 2) == '\r' ? 2 : 1;
        }
        return text.charAt(end - 1) == '\r' ? 1 : 0;
    }

    /** 0 = not a boundary line, 1 = opening boundary, 2 = closing boundary. */
    private static int matchDelimiter(String text, int pos, int eol, String delim) {
        if (!text.startsWith(delim, pos)) {
            return 0;
        }
        int p = pos + delim.length();
        boolean close = false;
        if (p + 2 <= eol && text.startsWith("--", p)) {
            close = true;
            p += 2;
        }
        while (p < eol && (text.charAt(p) == ' ' || text.charAt(p) == '\t')) {
            p++;
        }
        if (p != eol) {
            return 0;
        }
        return close ? 2 : 1;
    }

    // ------------------------------------------------------------------ body selection

    private static String contentType(Entity e) {
        String v = e.header("content-type");
        if (v == null) {
            return "text/plain";
        }
        int semi = v.indexOf(';');
        String ctype = (semi >= 0 ? v.substring(0, semi) : v).strip().toLowerCase(Locale.ROOT);
        int slash = ctype.indexOf('/');
        if (slash < 0 || ctype.indexOf('/', slash + 1) >= 0) {
            return "text/plain";
        }
        return ctype;
    }

    private static boolean isAttachment(Entity e) {
        String cd = e.header("content-disposition");
        if (cd == null) {
            return false;
        }
        int semi = cd.indexOf(';');
        return (semi >= 0 ? cd.substring(0, semi) : cd).strip().equalsIgnoreCase("attachment");
    }

    /** Python's EmailMessage._find_body for preference (plain, html): records the first of each. */
    private static void collect(Entity part, Entity top, Entity[] best) {
        if (isAttachment(part)) {
            return;
        }
        String ctype = contentType(part);
        int slash = ctype.indexOf('/');
        String maintype = ctype.substring(0, slash);
        String subtype = ctype.substring(slash + 1);
        if (maintype.equals("text")) {
            if (subtype.equals("plain") && best[0] == null) {
                best[0] = part;
            } else if (subtype.equals("html") && best[1] == null) {
                best[1] = part;
            }
            return;
        }
        if (!maintype.equals("multipart") || top.parts == null || part.parts == null) {
            return;
        }
        if (!subtype.equals("related")) {
            for (Entity sub : part.parts) {
                collect(sub, top, best);
            }
            return;
        }
        Entity candidate = null;
        String start = param(part.header("content-type"), "start");
        if (start != null && !start.isEmpty()) {
            for (Entity sub : part.parts) {
                if (start.equals(sub.header("content-id"))) {
                    candidate = sub;
                    break;
                }
            }
        }
        if (candidate == null && !part.parts.isEmpty()) {
            candidate = part.parts.get(0);
        }
        if (candidate != null) {
            collect(candidate, top, best);
        }
    }

    private static String textContent(Entity body) {
        byte[] raw = body.text.substring(body.bodyStart, body.bodyEnd).getBytes(StandardCharsets.ISO_8859_1);
        String cte = body.header("content-transfer-encoding");
        cte = cte == null ? "" : cte.strip().toLowerCase(Locale.ROOT);
        byte[] payload = switch (cte) {
            case "quoted-printable" -> decodeQuotedPrintable(raw);
            case "base64" -> decodeBase64(raw);
            default -> raw;
        };
        String charset = param(body.header("content-type"), "charset");
        if (charset == null) {
            charset = "ASCII";
        }
        Charset cs;
        try {
            cs = Charset.forName(charset);
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("unknown encoding: " + charset, ex);
        }
        return new String(payload, cs);
    }

    /** Parameter value from a header like "text/plain; charset=utf-8"; null if absent. */
    private static String param(String header, String name) {
        if (header == null) {
            return null;
        }
        int i = header.indexOf(';');
        if (i < 0) {
            return null;
        }
        i++;
        int n = header.length();
        while (i < n) {
            while (i < n && (header.charAt(i) == ' ' || header.charAt(i) == '\t' || header.charAt(i) == ';')) {
                i++;
            }
            int nameStart = i;
            while (i < n && header.charAt(i) != '=' && header.charAt(i) != ';') {
                i++;
            }
            String pname = header.substring(nameStart, i).strip();
            if (i >= n || header.charAt(i) == ';') {
                continue;
            }
            i++;
            while (i < n && (header.charAt(i) == ' ' || header.charAt(i) == '\t')) {
                i++;
            }
            String value;
            if (i < n && header.charAt(i) == '"') {
                StringBuilder q = new StringBuilder();
                i++;
                while (i < n && header.charAt(i) != '"') {
                    if (header.charAt(i) == '\\' && i + 1 < n) {
                        i++;
                    }
                    q.append(header.charAt(i));
                    i++;
                }
                if (i < n) {
                    i++;
                }
                while (i < n && header.charAt(i) != ';') {
                    i++;
                }
                value = q.toString();
            } else {
                int vs = i;
                while (i < n && header.charAt(i) != ';') {
                    i++;
                }
                value = header.substring(vs, i).strip();
            }
            if (pname.equalsIgnoreCase(name)) {
                return value;
            }
        }
        return null;
    }

    // ------------------------------------------------------------------ transfer encodings

    /** Same rules as CPython's binascii.a2b_qp (what quopri.decodestring uses). */
    static byte[] decodeQuotedPrintable(byte[] in) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(in.length);
        int n = in.length;
        int i = 0;
        while (i < n) {
            byte b = in[i];
            if (b != '=') {
                out.write(b);
                i++;
                continue;
            }
            i++;
            if (i >= n) {
                break;
            }
            byte c = in[i];
            if (c == '\n' || c == '\r') {
                if (c != '\n') {
                    while (i < n && in[i] != '\n') {
                        i++;
                    }
                }
                if (i < n) {
                    i++;
                }
            } else if (c == '=') {
                out.write('=');
                i++;
            } else if (i + 1 < n && hex(in[i]) >= 0 && hex(in[i + 1]) >= 0) {
                out.write(hex(in[i]) * 16 + hex(in[i + 1]));
                i += 2;
            } else {
                out.write('=');
            }
        }
        return out.toByteArray();
    }

    private static int hex(byte b) {
        if (b >= '0' && b <= '9') {
            return b - '0';
        }
        if (b >= 'a' && b <= 'f') {
            return b - 'a' + 10;
        }
        if (b >= 'A' && b <= 'F') {
            return b - 'A' + 10;
        }
        return -1;
    }

    private static byte[] decodeBase64(byte[] in) {
        try {
            return Base64.getMimeDecoder().decode(in);
        } catch (IllegalArgumentException e) {
            return in;
        }
    }

    // ------------------------------------------------------------------ header values

    /** Raw 8-bit header bytes are read as UTF-8 with replacement, like Python's sanitising. */
    private static String headerText(String raw) {
        return new String(raw.getBytes(StandardCharsets.ISO_8859_1), StandardCharsets.UTF_8);
    }

    /** An unstructured header (Subject): encoded words decoded, whitespace kept. */
    static String unstructured(String raw) {
        if (raw == null) {
            return "";
        }
        String s = headerText(raw);
        StringBuilder out = new StringBuilder();
        StringBuilder ws = new StringBuilder();
        boolean prevEncoded = false;
        int n = s.length();
        int i = 0;
        while (i < n) {
            char c = s.charAt(i);
            if (c == ' ' || c == '\t') {
                ws.append(c);
                i++;
                continue;
            }
            int j = i;
            while (j < n && s.charAt(j) != ' ' && s.charAt(j) != '\t') {
                j++;
            }
            String token = s.substring(i, j);
            String decoded = decodeEncodedWord(token);
            if (decoded != null) {
                if (!prevEncoded) {
                    out.append(ws);
                }
                out.append(decoded);
                prevEncoded = true;
            } else {
                out.append(ws).append(token);
                prevEncoded = false;
            }
            ws.setLength(0);
            i = j;
        }
        out.append(ws);
        return out.toString();
    }

    /** The decoded text if the whole token is a valid RFC 2047 encoded word, else null. */
    private static String decodeEncodedWord(String token) {
        Matcher m = ENCODED_WORD.matcher(token);
        if (!m.matches()) {
            return null;
        }
        String charset = m.group(1);
        int star = charset.indexOf('*');
        if (star >= 0) {
            charset = charset.substring(0, star);
        }
        try {
            byte[] bytes;
            if (m.group(2).equalsIgnoreCase("B")) {
                bytes = Base64.getMimeDecoder().decode(m.group(3));
            } else {
                bytes = decodeQuotedPrintable(m.group(3).replace('_', ' ').getBytes(StandardCharsets.ISO_8859_1));
            }
            Charset cs;
            try {
                cs = Charset.forName(charset);
            } catch (IllegalArgumentException unknownCharset) {
                cs = StandardCharsets.US_ASCII; // Python falls back to ASCII for an unknown charset
            }
            return new String(bytes, cs);
        } catch (IllegalArgumentException e) {
            return null;
        }
    }

    /** An address header (From/To) re-rendered the way Python's str(header) does. */
    static String addressHeader(String raw) {
        if (raw == null) {
            return "";
        }
        List<String> items = new ArrayList<>();
        for (String seg : splitTopLevel(headerText(raw))) {
            String r = renderSegment(seg);
            if (r != null && !r.isEmpty()) {
                items.add(r);
            }
        }
        return String.join(", ", items);
    }

    private static List<String> splitTopLevel(String s) {
        List<String> out = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        boolean quote = false;
        int angle = 0;
        int comment = 0;
        boolean group = false;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (quote) {
                cur.append(c);
                if (c == '\\' && i + 1 < s.length()) {
                    cur.append(s.charAt(++i));
                } else if (c == '"') {
                    quote = false;
                }
                continue;
            }
            if (comment > 0) {
                cur.append(c);
                if (c == '\\' && i + 1 < s.length()) {
                    cur.append(s.charAt(++i));
                } else if (c == '(') {
                    comment++;
                } else if (c == ')') {
                    comment--;
                }
                continue;
            }
            switch (c) {
                case '"' -> {
                    quote = true;
                    cur.append(c);
                }
                case '(' -> {
                    comment = 1;
                    cur.append(c);
                }
                case '<' -> {
                    angle++;
                    cur.append(c);
                }
                case '>' -> {
                    if (angle > 0) {
                        angle--;
                    }
                    cur.append(c);
                }
                case ':' -> {
                    if (angle == 0) {
                        group = true;
                    }
                    cur.append(c);
                }
                case ';' -> {
                    if (angle == 0) {
                        group = false;
                    }
                    cur.append(c);
                }
                case ',' -> {
                    if (angle == 0 && !group) {
                        out.add(cur.toString());
                        cur.setLength(0);
                    } else {
                        cur.append(c);
                    }
                }
                default -> cur.append(c);
            }
        }
        out.add(cur.toString());
        return out;
    }

    private static String renderSegment(String seg) {
        String s = stripComments(seg).strip();
        if (s.isEmpty()) {
            return null;
        }
        int colon = indexOfTopLevel(s, ':');
        if (colon >= 0) {
            String name = decodePhrase(s.substring(0, colon));
            String inner = s.substring(colon + 1).strip();
            if (inner.endsWith(";")) {
                inner = inner.substring(0, inner.length() - 1);
            }
            List<String> members = new ArrayList<>();
            for (String m : splitTopLevel(inner)) {
                String r = renderMailbox(stripComments(m).strip());
                if (r != null && !r.isEmpty()) {
                    members.add(r);
                }
            }
            String addresses = String.join(", ", members);
            String disp = hasSpecial(name) ? quote(name) : name;
            return disp + ":" + (addresses.isEmpty() ? "" : " " + addresses) + ";";
        }
        return renderMailbox(s);
    }

    private static String renderMailbox(String s) {
        if (s.isEmpty()) {
            return null;
        }
        int lt = indexOfTopLevel(s, '<');
        String display = "";
        String addr;
        if (lt >= 0) {
            int gt = s.indexOf('>', lt);
            if (gt < 0) {
                return s;
            }
            display = decodePhrase(s.substring(0, lt));
            addr = removeBlanks(s.substring(lt + 1, gt));
        } else {
            addr = removeBlanks(s);
        }
        if (display.isEmpty()) {
            return addr;
        }
        String disp = hasSpecial(display) ? quote(display) : display;
        return disp + " <" + (addr.equals("<>") ? "" : addr) + ">";
    }

    private static String decodePhrase(String raw) {
        StringBuilder out = new StringBuilder();
        int n = raw.length();
        int i = 0;
        boolean prevEncoded = false;
        boolean any = false;
        while (i < n) {
            char c = raw.charAt(i);
            if (c == ' ' || c == '\t') {
                i++;
                continue;
            }
            String piece;
            boolean encoded = false;
            if (c == '"') {
                StringBuilder q = new StringBuilder();
                i++;
                while (i < n && raw.charAt(i) != '"') {
                    if (raw.charAt(i) == '\\' && i + 1 < n) {
                        i++;
                    }
                    q.append(raw.charAt(i));
                    i++;
                }
                if (i < n) {
                    i++;
                }
                piece = q.toString();
            } else {
                int j = i;
                while (j < n && raw.charAt(j) != ' ' && raw.charAt(j) != '\t' && raw.charAt(j) != '"') {
                    j++;
                }
                String token = raw.substring(i, j);
                i = j;
                String decoded = decodeEncodedWord(token);
                if (decoded != null) {
                    piece = decoded;
                    encoded = true;
                } else {
                    piece = token;
                }
            }
            if (any && !(prevEncoded && encoded)) {
                out.append(' ');
            }
            out.append(piece);
            any = true;
            prevEncoded = encoded;
        }
        return out.toString();
    }

    private static String stripComments(String s) {
        StringBuilder out = new StringBuilder();
        boolean quote = false;
        int depth = 0;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (depth > 0) {
                if (c == '\\' && i + 1 < s.length()) {
                    i++;
                } else if (c == '(') {
                    depth++;
                } else if (c == ')') {
                    depth--;
                }
                continue;
            }
            if (quote) {
                out.append(c);
                if (c == '\\' && i + 1 < s.length()) {
                    out.append(s.charAt(++i));
                } else if (c == '"') {
                    quote = false;
                }
                continue;
            }
            if (c == '"') {
                quote = true;
                out.append(c);
            } else if (c == '(') {
                depth = 1;
            } else {
                out.append(c);
            }
        }
        return out.toString();
    }

    /** First occurrence of the character outside quoted strings and angle brackets, or -1. */
    private static int indexOfTopLevel(String s, char target) {
        boolean quote = false;
        int angle = 0;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (quote) {
                if (c == '\\') {
                    i++;
                } else if (c == '"') {
                    quote = false;
                }
                continue;
            }
            if (c == '"') {
                quote = true;
            } else if (c == '<') {
                if (target == '<' && angle == 0) {
                    return i;
                }
                angle++;
            } else if (c == '>') {
                if (angle > 0) {
                    angle--;
                }
            } else if (c == target && angle == 0) {
                return i;
            }
        }
        return -1;
    }

    private static String removeBlanks(String s) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c != ' ' && c != '\t') {
                out.append(c);
            }
        }
        return out.toString();
    }

    private static boolean hasSpecial(String v) {
        for (int i = 0; i < v.length(); i++) {
            if (SPECIALS.indexOf(v.charAt(i)) >= 0) {
                return true;
            }
        }
        return false;
    }

    private static String quote(String v) {
        return "\"" + v.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }
}
