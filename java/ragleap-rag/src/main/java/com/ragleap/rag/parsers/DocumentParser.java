package com.ragleap.rag.parsers;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.util.DefaultIndenter;
import com.fasterxml.jackson.core.util.DefaultPrettyPrinter;
import com.fasterxml.jackson.core.util.Separators;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectWriter;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLMapper;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;
import java.util.logging.Logger;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Document text extraction. Java port of ragleap-rag's parsers.py (extract_text).
 *
 * <p>27 of the Python package's 28 formats are supported. Parquet is deliberately
 * not supported (Java Parquet readers pull in a very heavy Hadoop dependency
 * tree). Legacy .xls needs the optional Apache POI dependency.
 *
 * <p>Errors: where Python raises ValueError, this class throws
 * IllegalArgumentException with the same message wording.
 *
 * <p>Not supported: legacy binary .doc and .ppt, same as Python.
 */
public final class DocumentParser {

    private static final Logger logger = Logger.getLogger(DocumentParser.class.getName());

    /** Formats implemented in this port so far. Grows as batches land. */
    public static final Set<String> SUPPORTED_EXTENSIONS = Collections.unmodifiableSet(new TreeSet<>(List.of(
            ".txt", ".md", ".sql", ".csv", ".tsv", ".json", ".yaml", ".yml", ".vtt", ".srt", ".zip", ".rtf",
            ".html", ".htm", ".xml", ".xsl", ".xslt", ".pdf",
            ".docx", ".pptx", ".xlsx", ".odt", ".ods", ".odp", ".epub",
            ".xls", ".eml")));

    private static final Set<String> UNSUPPORTED_LEGACY = Set.of(".doc", ".ppt");

    /** Default archive limits, the same as the Python package's MAX_ZIP_MEMBERS and MAX_ZIP_UNCOMPRESSED_BYTES. */
    public static final int DEFAULT_MAX_ZIP_MEMBERS = 1000;
    public static final long DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES = 100L * 1024 * 1024;
    private static volatile int maxZipMembers = DEFAULT_MAX_ZIP_MEMBERS;
    private static volatile long maxZipUncompressedBytes = DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES;
    private static final Set<String> ZIP_BASED_EXTENSIONS =
            Set.of(".zip", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub");

    /**
     * Sets the archive limits for zip-based formats (.zip, .docx, .xlsx, .pptx, .odt, .ods, .odp, .epub).
     * Process-wide, like assigning the Python module constants.
     */
    public static void setZipLimits(int maxMembers, long maxUncompressedBytes) {
        if (maxMembers < 0 || maxUncompressedBytes < 0) {
            throw new IllegalArgumentException("Archive limits must not be negative");
        }
        maxZipMembers = maxMembers;
        maxZipUncompressedBytes = maxUncompressedBytes;
    }

    private static final ObjectMapper JSON = JsonMapper.builder()
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
            .build();
    private static final YAMLMapper YAML = new YAMLMapper();

    /** Matches Python's json.dumps(indent=2, ensure_ascii=False) layout. */
    private static final ObjectWriter PYTHON_STYLE_WRITER = buildPythonStyleWriter();

    /** Same line boundaries as Python's str.splitlines(). */
    private static final Pattern LINE_BREAKS =
            Pattern.compile("\r\n|[\n\r\u000B\u000C\u001C\u001D\u001E\u0085\u2028\u2029]");

    private DocumentParser() {
    }

    private static ObjectWriter buildPythonStyleWriter() {
        DefaultPrettyPrinter printer = new DefaultPrettyPrinter(
                Separators.createDefaultInstance()
                        .withObjectFieldValueSpacing(Separators.Spacing.AFTER)
                        .withObjectEmptySeparator("")
                        .withArrayEmptySeparator(""));
        DefaultIndenter indenter = new DefaultIndenter("  ", "\n");
        printer.indentObjectsWith(indenter);
        printer.indentArraysWith(indenter);
        return JSON.writer(printer);
    }

    /** Extract plain text from raw file bytes, dispatching on the file extension. */
    public static String extractText(String filename, byte[] rawBytes) {
        Objects.requireNonNull(filename, "filename");
        Objects.requireNonNull(rawBytes, "rawBytes");
        String ext = extensionOf(filename);

        if (UNSUPPORTED_LEGACY.contains(ext)) {
            throw new IllegalArgumentException(
                    "'" + ext + "' (legacy binary Office format) is not supported — no reliable "
                            + "parser exists. Convert to the modern equivalent first (.docx/.pptx), "
                            + "e.g. via LibreOffice headless: "
                            + "'soffice --headless --convert-to docx yourfile.doc'");
        }
        if (ext.equals(".parquet")) {
            throw new IllegalArgumentException(
                    "Parquet is not supported in the Java port (Java Parquet readers need a very "
                            + "heavy Hadoop dependency tree). Convert to CSV first.");
        }

        if (ZIP_BASED_EXTENSIONS.contains(ext)) {
            checkZipLimits(rawBytes);
        }

        return switch (ext) {
            case ".txt", ".md", ".sql" -> extractTxt(rawBytes);
            case ".csv" -> extractCsv(rawBytes, ',');
            case ".tsv" -> extractCsv(rawBytes, '\t');
            case ".json" -> extractJson(rawBytes);
            case ".yaml", ".yml" -> extractYaml(rawBytes);
            case ".vtt", ".srt" -> extractSubtitle(rawBytes);
            case ".zip" -> extractZip(rawBytes);
            case ".rtf" -> extractRtf(rawBytes);
            case ".html", ".htm" -> MarkupExtractor.html(rawBytes);
            case ".xml", ".xsl", ".xslt" -> MarkupExtractor.xml(rawBytes);
            case ".pdf" -> PdfExtractor.extract(rawBytes);
            case ".docx" -> DocxExtractor.extract(rawBytes);
            case ".pptx" -> PptxExtractor.extract(rawBytes);
            case ".xlsx" -> XlsxExtractor.extract(rawBytes);
            case ".odt", ".odp" -> OdfExtractor.paragraphs(rawBytes, ext.equals(".odt") ? "ODT" : "ODP");
            case ".ods" -> OdfExtractor.spreadsheet(rawBytes);
            case ".epub" -> EpubExtractor.extract(rawBytes);
            case ".xls" -> extractXls(rawBytes);
            case ".eml" -> EmlExtractor.extract(rawBytes);
            default -> throw new IllegalArgumentException(
                    "Unsupported file type '" + ext + "'. Supported: "
                            + String.join(", ", SUPPORTED_EXTENSIONS) + ".");
        };
    }

    /** Mirrors Python: text after the last dot, lower-cased, with a leading dot ("." if none). */
    static String extensionOf(String filename) {
        String lower = filename.toLowerCase(Locale.ROOT);
        int idx = lower.lastIndexOf('.');
        return idx >= 0 ? "." + lower.substring(idx + 1) : ".";
    }

    static String extractTxt(byte[] rawBytes) {
        try {
            return StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(rawBytes))
                    .toString();
        } catch (CharacterCodingException e) {
            logger.warning("UTF-8 decode failed, retrying with latin-1");
            return new String(rawBytes, StandardCharsets.ISO_8859_1);
        }
    }

    static String extractCsv(byte[] rawBytes, char delimiter) {
        List<List<String>> rows = parseCsv(extractTxt(rawBytes), delimiter);
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < rows.size(); i++) {
            if (i > 0) {
                out.append('\n');
            }
            out.append(String.join("\t", rows.get(i)));
        }
        return out.toString();
    }

    /**
     * Small CSV reader matching Python's csv.reader defaults: double-quote quoting with
     * doubled quotes as escapes, newlines allowed inside quoted fields, a blank line
     * yields an empty row, and a quote in the middle of an unquoted field is literal.
     */
    private static List<List<String>> parseCsv(String text, char delimiter) {
        List<List<String>> rows = new ArrayList<>();
        List<String> fields = new ArrayList<>();
        StringBuilder field = new StringBuilder();
        boolean inQuotes = false;
        boolean atFieldStart = true;
        boolean started = false;
        int n = text.length();
        for (int i = 0; i < n; i++) {
            char c = text.charAt(i);
            if (inQuotes) {
                if (c == '"') {
                    if (i + 1 < n && text.charAt(i + 1) == '"') {
                        field.append('"');
                        i++;
                    } else {
                        inQuotes = false;
                    }
                } else {
                    field.append(c);
                }
                continue;
            }
            if (c == '\n' || c == '\r') {
                if (c == '\r' && i + 1 < n && text.charAt(i + 1) == '\n') {
                    i++;
                }
                if (started) {
                    fields.add(field.toString());
                }
                rows.add(fields);
                fields = new ArrayList<>();
                field.setLength(0);
                atFieldStart = true;
                started = false;
                continue;
            }
            started = true;
            if (c == delimiter) {
                fields.add(field.toString());
                field.setLength(0);
                atFieldStart = true;
            } else if (c == '"' && atFieldStart) {
                inQuotes = true;
                atFieldStart = false;
            } else {
                field.append(c);
                atFieldStart = false;
            }
        }
        if (started) {
            fields.add(field.toString());
            rows.add(fields);
        }
        return rows;
    }

    static String extractJson(byte[] rawBytes) {
        try {
            JsonNode node = JSON.readTree(extractTxt(rawBytes));
            if (node == null || node.isMissingNode()) {
                throw new IllegalArgumentException("Invalid JSON: document is empty");
            }
            return PYTHON_STYLE_WRITER.writeValueAsString(node);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("Invalid JSON: " + e.getOriginalMessage(), e);
        }
    }

    static String extractYaml(byte[] rawBytes) {
        try {
            JsonNode node = YAML.readTree(extractTxt(rawBytes));
            if (node == null || node.isMissingNode()) {
                return "null";
            }
            return PYTHON_STYLE_WRITER.writeValueAsString(node);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("Invalid YAML: " + e.getOriginalMessage(), e);
        }
    }

    /** Strips timestamps and cue numbers from .vtt/.srt files, keeping the spoken text. */
    static String extractSubtitle(byte[] rawBytes) {
        List<String> kept = new ArrayList<>();
        for (String line : LINE_BREAKS.split(extractTxt(rawBytes), -1)) {
            String stripped = PyText.strip(line);
            if (stripped.isEmpty() || stripped.equals("WEBVTT")) {
                continue;
            }
            if (isAllDigits(stripped)) {
                continue;
            }
            if (stripped.contains("-->")) {
                continue;
            }
            kept.add(stripped);
        }
        return String.join("\n", kept);
    }

    private static boolean isAllDigits(String s) {
        for (int i = 0; i < s.length(); i++) {
            if (!Character.isDigit(s.charAt(i))) {
                return false;
            }
        }
        return !s.isEmpty();
    }

    static String extractRtf(byte[] rawBytes) {
        return RtfConverter.rtfToText(extractTxt(rawBytes));
    }

    private static String extractXls(byte[] rawBytes) {
        try {
            return XlsExtractor.extract(rawBytes);
        } catch (NoClassDefFoundError e) {
            throw new IllegalArgumentException("Apache POI is required for .xls files — add the optional "
                    + "dependency org.apache.poi:poi to your project", e);
        }
    }

    /** Extracts and concatenates text from every supported file inside the zip. */
    static String extractZip(byte[] rawBytes) {
        List<String> parts = new ArrayList<>();
        long budget = maxZipUncompressedBytes;
        try (ZipInputStream zis = new ZipInputStream(new ByteArrayInputStream(rawBytes))) {
            ZipEntry entry;
            while ((entry = zis.getNextEntry()) != null) {
                String name = entry.getName();
                if (name.endsWith("/")) {
                    continue;
                }
                String ext = extensionOf(name);
                if (!SUPPORTED_EXTENSIONS.contains(ext) || ext.equals(".zip")) {
                    continue;
                }
                try {
                    byte[] inner = zis.readNBytes((int) Math.min(budget + 1, Integer.MAX_VALUE - 8L));
                    if (inner.length > budget) {
                        throw new ZipLimitException("Archive member data exceeds the "
                                + maxZipUncompressedBytes + "-byte uncompressed limit.");
                    }
                    budget -= inner.length;
                    String innerText = extractText(name, inner);
                    if (!PyText.isBlank(innerText)) {
                        parts.add("[File: " + name + "]\n" + innerText);
                    }
                } catch (ZipLimitException e) {
                    throw e;
                } catch (Exception e) {
                    logger.warning("Skipping '" + name + "' inside zip — extraction failed: " + e.getMessage());
                }
            }
        } catch (IOException e) {
            throw new IllegalArgumentException("Could not read zip: " + e.getMessage(), e);
        }
        if (parts.isEmpty()) {
            throw new IllegalArgumentException("No extractable text found in any file inside this zip.");
        }
        return String.join("\n\n", parts);
    }

    /**
     * Rejects an archive with too many members or too much declared uncompressed data, before any
     * extraction (the Python package's _check_zip_limits). An archive that cannot be read as a zip is
     * left to the format's own parser to report.
     */
    static void checkZipLimits(byte[] rawBytes) {
        java.nio.file.Path tmp = null;
        try {
            tmp = java.nio.file.Files.createTempFile("ragleap-zipcheck-", ".zip");
            java.nio.file.Files.write(tmp, rawBytes);
            try (java.util.zip.ZipFile zf = new java.util.zip.ZipFile(tmp.toFile())) {
                int count = zf.size();
                if (count > maxZipMembers) {
                    throw new ZipLimitException("Archive has " + count + " members (limit " + maxZipMembers + ").");
                }
                long total = 0;
                java.util.Enumeration<? extends ZipEntry> entries = zf.entries();
                while (entries.hasMoreElements()) {
                    long size = entries.nextElement().getSize();
                    if (size > 0) {
                        total += size;
                    }
                }
                if (total > maxZipUncompressedBytes) {
                    throw new ZipLimitException("Archive declares " + total
                            + " bytes uncompressed (limit " + maxZipUncompressedBytes + ").");
                }
            }
        } catch (java.util.zip.ZipException e) {
            // not a readable archive: the format's own parser reports that
        } catch (IOException e) {
            throw new IllegalArgumentException("Could not read archive: " + e.getMessage(), e);
        } finally {
            if (tmp != null) {
                try {
                    java.nio.file.Files.deleteIfExists(tmp);
                } catch (IOException ignored) {
                    // best effort
                }
            }
        }
    }
}
