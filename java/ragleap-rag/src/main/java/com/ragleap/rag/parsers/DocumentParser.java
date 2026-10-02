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
 * <p>This is being ported in batches. SUPPORTED_EXTENSIONS lists the formats
 * implemented so far; formats the Python package supports but this port has not
 * reached yet raise an IllegalArgumentException saying so. Parquet is
 * deliberately deferred (Java Parquet readers pull in a very heavy Hadoop
 * dependency tree).
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
            ".txt", ".md", ".sql", ".csv", ".tsv", ".json", ".yaml", ".yml", ".vtt", ".srt", ".zip", ".rtf")));

    /** Supported by the Python package, planned for this port, not written yet. */
    private static final Set<String> NOT_YET_PORTED = Set.of(
            ".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".html", ".htm", ".xml", ".xsl", ".xslt",
            ".odt", ".ods", ".odp", ".eml", ".epub");

    private static final Set<String> UNSUPPORTED_LEGACY = Set.of(".doc", ".ppt");

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
        if (NOT_YET_PORTED.contains(ext)) {
            throw new IllegalArgumentException(
                    "'" + ext + "' parsing is not yet available in the Java port of ragleap-rag.");
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
            String stripped = line.strip();
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

    /** Extracts and concatenates text from every supported file inside the zip. */
    static String extractZip(byte[] rawBytes) {
        List<String> parts = new ArrayList<>();
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
                    String innerText = extractText(name, zis.readAllBytes());
                    if (!innerText.isBlank()) {
                        parts.add("[File: " + name + "]\n" + innerText);
                    }
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
}
