package com.ragleap.rag.ingestion;

import javax.imageio.ImageIO;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.Objects;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;

/**
 * OCR text extraction. Java port of ragleap-rag's ocr.py (extract_text_from_image), which calls the
 * Tesseract binary through pytesseract. This class runs the same binary the same way
 * ({@code tesseract <image> <output> txt}, default language) and returns its text unchanged, so the
 * result ends with the newline and form feed Tesseract writes, exactly like Python.
 *
 * <p>Requires the Tesseract binary on the PATH. Errors that are ValueError in Python throw
 * IllegalArgumentException with the same wording.
 *
 * <p>Known differences from Python: the original image bytes are passed to Tesseract as they are (Python
 * re-encodes the image in its own format first, which for JPEG is a second lossy pass), except that a PNG
 * with an alpha channel is flattened onto a white background, as pytesseract does. A transparent WebP is
 * not flattened. Formats that Pillow opens but pytesseract rejects report "Could not open image data"
 * here. A 300 second timeout is added (Python has none).
 */
public final class OcrExtractor {

    public static final String DEFAULT_TESSERACT_COMMAND = "tesseract";
    static final long TIMEOUT_SECONDS = 300;
    private static final String HINT = "If this is a 'tesseract not found' error, install the Tesseract binary itself "
            + "(e.g. 'apt install tesseract-ocr' on Debian/Ubuntu).";

    private OcrExtractor() {
    }

    /** Runs OCR on image bytes and returns the extracted text. */
    public static String extractText(byte[] rawBytes) {
        return extractText(rawBytes, DEFAULT_TESSERACT_COMMAND);
    }

    /** Same as {@link #extractText(byte[])} with an explicit Tesseract command or path. */
    public static String extractText(byte[] rawBytes, String tesseractCommand) {
        Objects.requireNonNull(rawBytes, "rawBytes");
        Objects.requireNonNull(tesseractCommand, "tesseractCommand");
        String format = detectFormat(rawBytes);
        if (format == null) {
            throw new IllegalArgumentException("Could not open image data: cannot identify image file");
        }
        byte[] image = rawBytes;
        if (format.equals("PNG") && pngHasAlpha(rawBytes)) {
            image = flattenOnWhite(rawBytes);
        }
        String text = runTesseract(image, extensionOf(format), tesseractCommand);
        if (isBlank(text)) {
            throw new IllegalArgumentException("OCR found no readable text in this image.");
        }
        return text;
    }

    private static String runTesseract(byte[] image, String extension, String command) {
        Path dir = null;
        try {
            dir = Files.createTempDirectory("ragleap-ocr-");
            Path input = dir.resolve("input." + extension);
            Files.write(input, image);
            Path outBase = dir.resolve("out");
            Path log = dir.resolve("tesseract.log");
            ProcessBuilder pb = new ProcessBuilder(command, input.toString(), outBase.toString(), "txt");
            pb.redirectErrorStream(true);
            pb.redirectOutput(log.toFile());
            Process proc;
            try {
                proc = pb.start();
            } catch (IOException e) {
                throw failed("tesseract is not installed or it's not in your PATH (" + e.getMessage() + ")", e);
            }
            if (!proc.waitFor(TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
                proc.destroyForcibly();
                throw failed("tesseract did not finish within " + TIMEOUT_SECONDS + " seconds", null);
            }
            if (proc.exitValue() != 0) {
                throw failed("tesseract exited with status " + proc.exitValue() + ": " + tail(log), null);
            }
            byte[] out = Files.readAllBytes(dir.resolve("out.txt"));
            try {
                return StandardCharsets.UTF_8.newDecoder()
                        .onMalformedInput(CodingErrorAction.REPORT)
                        .onUnmappableCharacter(CodingErrorAction.REPORT)
                        .decode(ByteBuffer.wrap(out)).toString();
            } catch (CharacterCodingException e) {
                throw failed("tesseract output is not valid UTF-8", e);
            }
        } catch (IOException e) {
            throw failed(String.valueOf(e.getMessage()), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw failed("interrupted while waiting for tesseract", e);
        } finally {
            deleteQuietly(dir);
        }
    }

    private static IllegalArgumentException failed(String detail, Throwable cause) {
        return new IllegalArgumentException("OCR failed: " + detail + ". " + HINT, cause);
    }

    private static String tail(Path log) {
        try {
            String s = new String(Files.readAllBytes(log), StandardCharsets.UTF_8).strip();
            return s.length() <= 500 ? s : s.substring(s.length() - 500);
        } catch (IOException e) {
            return "(no output)";
        }
    }

    /** The image format from its leading bytes, or null if it is not one tesseract's wrapper accepts. */
    static String detectFormat(byte[] b) {
        if (startsWith(b, 0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A)) {
            return "PNG";
        }
        if (startsWith(b, 0xFF, 0xD8, 0xFF)) {
            return "JPEG";
        }
        if (startsWith(b, 'G', 'I', 'F', '8') && b.length >= 6 && (b[4] == '7' || b[4] == '9') && b[5] == 'a') {
            return "GIF";
        }
        if (startsWith(b, 'B', 'M') && b.length >= 14 && b[6] == 0 && b[7] == 0 && b[8] == 0 && b[9] == 0) {
            return "BMP";
        }
        if (startsWith(b, 'I', 'I', 0x2A, 0x00) || startsWith(b, 'M', 'M', 0x00, 0x2A)) {
            return "TIFF";
        }
        if (b.length >= 12 && startsWith(b, 'R', 'I', 'F', 'F') && b[8] == 'W' && b[9] == 'E' && b[10] == 'B' && b[11] == 'P') {
            return "WEBP";
        }
        if (b.length >= 3 && b[0] == 'P' && b[1] >= '1' && b[1] <= '6'
                && (b[2] == '\n' || b[2] == '\r' || b[2] == ' ' || b[2] == '\t')) {
            return "PNM";
        }
        return null;
    }

    private static boolean startsWith(byte[] b, int... prefix) {
        if (b.length < prefix.length) {
            return false;
        }
        for (int i = 0; i < prefix.length; i++) {
            if ((b[i] & 0xFF) != prefix[i]) {
                return false;
            }
        }
        return true;
    }

    private static String extensionOf(String format) {
        return switch (format) {
            case "PNG" -> "png";
            case "JPEG" -> "jpg";
            case "GIF" -> "gif";
            case "BMP" -> "bmp";
            case "TIFF" -> "tiff";
            case "WEBP" -> "webp";
            default -> "pnm";
        };
    }

    /** True for PNG colour types 4 (grey + alpha) and 6 (RGBA); palette PNGs are not flattened, like pytesseract. */
    static boolean pngHasAlpha(byte[] b) {
        if (b.length < 26 || b[12] != 'I' || b[13] != 'H' || b[14] != 'D' || b[15] != 'R') {
            return false;
        }
        int colorType = b[25] & 0xFF;
        return colorType == 4 || colorType == 6;
    }

    /** Composites a PNG with transparency onto a white background and returns it as an opaque PNG. */
    static byte[] flattenOnWhite(byte[] png) {
        BufferedImage src;
        try {
            src = ImageIO.read(new ByteArrayInputStream(png));
        } catch (IOException | RuntimeException e) {
            throw new IllegalArgumentException("Could not open image data: " + e.getMessage(), e);
        }
        if (src == null) {
            throw new IllegalArgumentException("Could not open image data: cannot decode PNG");
        }
        BufferedImage flat = new BufferedImage(src.getWidth(), src.getHeight(), BufferedImage.TYPE_INT_RGB);
        Graphics2D g = flat.createGraphics();
        try {
            g.setColor(Color.WHITE);
            g.fillRect(0, 0, flat.getWidth(), flat.getHeight());
            g.drawImage(src, 0, 0, null);
        } finally {
            g.dispose();
        }
        try {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            ImageIO.write(flat, "png", out);
            return out.toByteArray();
        } catch (IOException e) {
            throw new IllegalArgumentException("Could not open image data: " + e.getMessage(), e);
        }
    }

    /** Python-style blank test: strip() also removes the form feed and non-breaking spaces. */
    private static boolean isBlank(String s) {
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (!(Character.isWhitespace(c) || Character.isSpaceChar(c) || c == 0x85)) {
                return false;
            }
        }
        return true;
    }

    private static void deleteQuietly(Path dir) {
        if (dir == null) {
            return;
        }
        try (Stream<Path> walk = Files.walk(dir)) {
            walk.sorted(Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (IOException ignored) {
                    // best effort
                }
            });
        } catch (IOException ignored) {
            // best effort
        }
    }
}
