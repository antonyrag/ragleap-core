package com.ragleap.rag.ingestion;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Tests that need no Tesseract run everywhere; the live one skips itself when the binary is missing. */
class OcrExtractorTest {

    static boolean tesseractAvailable() {
        try {
            Process p = new ProcessBuilder("tesseract", "--version")
                    .redirectErrorStream(true).redirectOutput(ProcessBuilder.Redirect.DISCARD).start();
            return p.waitFor(20, TimeUnit.SECONDS) && p.exitValue() == 0;
        } catch (Exception e) {
            return false;
        }
    }

    private static byte[] png(BufferedImage img) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        ImageIO.write(img, "png", bos);
        return bos.toByteArray();
    }

    private static BufferedImage solid(int type, int w, int h, int argb) {
        BufferedImage img = new BufferedImage(w, h, type);
        for (int x = 0; x < w; x++) {
            for (int y = 0; y < h; y++) {
                img.setRGB(x, y, argb);
            }
        }
        return img;
    }

    @Test void garbageBytesAreRejectedLikePythonsCouldNotOpenError() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> OcrExtractor.extractText("this is not an image".getBytes(StandardCharsets.UTF_8)));
        assertTrue(ex.getMessage().startsWith("Could not open image data: "));
    }

    @Test void emptyBytesAreRejected() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () -> OcrExtractor.extractText(new byte[0]));
        assertTrue(ex.getMessage().startsWith("Could not open image data: "));
    }

    @Test void formatsAreRecognisedFromTheirSignatures() {
        assertEquals("PNG", OcrExtractor.detectFormat(new byte[] {(byte) 0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A}));
        assertEquals("JPEG", OcrExtractor.detectFormat(new byte[] {(byte) 0xFF, (byte) 0xD8, (byte) 0xFF, (byte) 0xE0}));
        assertEquals("GIF", OcrExtractor.detectFormat("GIF89a".getBytes(StandardCharsets.US_ASCII)));
        assertEquals("GIF", OcrExtractor.detectFormat("GIF87a".getBytes(StandardCharsets.US_ASCII)));
        assertEquals("BMP", OcrExtractor.detectFormat(new byte[] {'B', 'M', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}));
        assertEquals("TIFF", OcrExtractor.detectFormat(new byte[] {'I', 'I', 0x2A, 0x00}));
        assertEquals("TIFF", OcrExtractor.detectFormat(new byte[] {'M', 'M', 0x00, 0x2A}));
        assertEquals("WEBP", OcrExtractor.detectFormat("RIFF\0\0\0\0WEBP".getBytes(StandardCharsets.ISO_8859_1)));
        assertEquals("PNM", OcrExtractor.detectFormat("P6\n1 1\n255\n".getBytes(StandardCharsets.US_ASCII)));
        assertNull(OcrExtractor.detectFormat("hello".getBytes(StandardCharsets.US_ASCII)));
        assertNull(OcrExtractor.detectFormat("BM is just text".getBytes(StandardCharsets.US_ASCII)));
    }

    @Test void pngColourTypeDecidesWhetherTheImageIsFlattened() throws IOException {
        assertTrue(OcrExtractor.pngHasAlpha(png(solid(BufferedImage.TYPE_INT_ARGB, 40, 20, 0x00000000))));
        assertFalse(OcrExtractor.pngHasAlpha(png(solid(BufferedImage.TYPE_INT_RGB, 40, 20, 0xFFFFFFFF))));
        assertFalse(OcrExtractor.pngHasAlpha(png(solid(BufferedImage.TYPE_BYTE_GRAY, 40, 20, 0xFF808080))));
    }

    @Test void transparentPixelsAreFlattenedOntoWhiteAndOpaqueOnesKept() throws IOException {
        BufferedImage argb = solid(BufferedImage.TYPE_INT_ARGB, 40, 20, 0x00000000);
        argb.setRGB(5, 5, 0xFF000000);
        BufferedImage flat = ImageIO.read(new ByteArrayInputStream(OcrExtractor.flattenOnWhite(png(argb))));
        assertEquals(0xFFFFFF, flat.getRGB(0, 0) & 0xFFFFFF);
        assertEquals(0x000000, flat.getRGB(5, 5) & 0xFFFFFF);
        assertFalse(flat.getColorModel().hasAlpha());
    }

    @Test void aMissingTesseractBinaryGivesAClearError() throws IOException {
        byte[] image = png(solid(BufferedImage.TYPE_INT_RGB, 600, 200, 0xFFFFFFFF));
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> OcrExtractor.extractText(image, "definitely-not-a-tesseract-binary-xyz"));
        assertTrue(ex.getMessage().startsWith("OCR failed: tesseract is not installed"));
        assertTrue(ex.getMessage().contains("install the Tesseract binary itself"));
    }

    @Test
    @EnabledIf("tesseractAvailable")
    void aBlankImageHasNoReadableText() throws IOException {
        byte[] image = png(solid(BufferedImage.TYPE_INT_RGB, 600, 200, 0xFFFFFFFF));
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () -> OcrExtractor.extractText(image));
        assertEquals("OCR found no readable text in this image.", ex.getMessage());
    }
}
