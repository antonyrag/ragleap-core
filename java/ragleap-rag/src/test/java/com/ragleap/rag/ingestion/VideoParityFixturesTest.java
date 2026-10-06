package com.ragleap.rag.ingestion;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Compares VideoAudioExtractor with the real Python video.py on fixture videos: X, plus X.expected (the exact
 * MP3 bytes Python produced) or X.error (its message). The MP3 bytes must be identical. Error messages that
 * contain ffmpeg's own output are compared by their prefix. Set RAGLEAP_VIDEO_PARITY_DIR; skipped without it
 * or without ffmpeg.
 */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_VIDEO_PARITY_DIR", matches = ".+")
class VideoParityFixturesTest {

    private static String describeDifference(byte[] want, byte[] got) {
        int n = Math.min(want.length, got.length);
        int i = 0;
        while (i < n && want[i] == got[i]) {
            i++;
        }
        return "python=" + want.length + " bytes, java=" + got.length + " bytes, first difference at offset " + i
                + (i < n ? " (python " + String.format("%02x", want[i] & 0xFF) + " vs java " + String.format("%02x", got[i] & 0xFF) + ")" : "");
    }

    @Test
    void matchesRealPythonOutputOnEveryFixture() throws IOException {
        Assumptions.assumeTrue(VideoAudioExtractorTest.ffmpegAvailable(), "ffmpeg is not installed - skipping video parity check");
        Path dir = Path.of(System.getenv("RAGLEAP_VIDEO_PARITY_DIR"));
        List<Path> files;
        try (Stream<Path> s = Files.list(dir)) {
            files = s.sorted().toList();
        }
        List<String> failures = new ArrayList<>();
        int checked = 0;
        for (Path file : files) {
            String name = file.getFileName().toString();
            if (name.endsWith(".expected") || name.endsWith(".error")) {
                continue;
            }
            Path expected = file.resolveSibling(name + ".expected");
            Path error = file.resolveSibling(name + ".error");
            if (!Files.exists(expected) && !Files.exists(error)) {
                continue;
            }
            checked++;
            byte[] raw = Files.readAllBytes(file);
            try {
                byte[] got = VideoAudioExtractor.extractAudio(raw, name);
                if (!Files.exists(expected)) {
                    failures.add(name + ": Python raised an error but Java returned " + got.length + " bytes");
                } else {
                    byte[] want = Files.readAllBytes(expected);
                    if (!Arrays.equals(want, got)) {
                        failures.add(name + ": MP3 bytes differ: " + describeDifference(want, got));
                    }
                }
            } catch (IllegalArgumentException e) {
                if (Files.exists(error)) {
                    String want = Files.readString(error, StandardCharsets.UTF_8);
                    boolean ok = want.startsWith("ffmpeg audio extraction failed: ")
                            ? e.getMessage().startsWith("ffmpeg audio extraction failed: ")
                            : want.equals(e.getMessage());
                    if (!ok) {
                        failures.add(name + ": error differs:\n   python = " + want + "\n   java   = " + e.getMessage());
                    }
                } else {
                    failures.add(name + ": Java raised '" + e.getMessage() + "' but Python returned audio");
                }
            }
        }
        System.out.println("VIDEO PARITY: checked=" + checked + " failures=" + failures.size());
        assertTrue(checked > 0, "no fixtures were checked");
        assertTrue(failures.isEmpty(), "Differences from real Python output:\n" + String.join("\n", failures));
    }
}
