package com.ragleap.rag.ingestion;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Tests that need no ffmpeg run everywhere; the others skip themselves when the binary is missing. */
class VideoAudioExtractorTest {

    @TempDir
    Path tmp;

    static boolean ffmpegAvailable() {
        try {
            Process p = new ProcessBuilder("ffmpeg", "-version")
                    .redirectErrorStream(true).redirectOutput(ProcessBuilder.Redirect.DISCARD).start();
            return p.waitFor(20, TimeUnit.SECONDS) && p.exitValue() == 0;
        } catch (Exception e) {
            return false;
        }
    }

    private byte[] makeVideo(boolean withAudio) throws Exception {
        Path out = tmp.resolve(withAudio ? "with-audio.mp4" : "no-audio.mp4");
        String[] cmd = withAudio
                ? new String[] {"ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "mpeg4", "-c:a", "aac", "-shortest", out.toString()}
                : new String[] {"ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
                        "-c:v", "mpeg4", out.toString()};
        Process p = new ProcessBuilder(cmd).redirectErrorStream(true).redirectOutput(ProcessBuilder.Redirect.DISCARD).start();
        assertTrue(p.waitFor(60, TimeUnit.SECONDS) && p.exitValue() == 0, "could not generate the test video");
        return Files.readAllBytes(out);
    }

    private static boolean looksLikeMp3(byte[] b) {
        boolean id3 = b.length > 3 && b[0] == 'I' && b[1] == 'D' && b[2] == '3';
        boolean frame = b.length > 2 && (b[0] & 0xFF) == 0xFF && (b[1] & 0xE0) == 0xE0;
        return id3 || frame;
    }

    @Test void aMissingFfmpegBinaryGivesPythonsMessage() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> VideoAudioExtractor.extractAudio(new byte[] {1, 2, 3}, "a.mp4", "definitely-not-an-ffmpeg-binary-xyz"));
        assertEquals("ffmpeg is required for video ingestion but is not installed on this system. "
                + "Install it (e.g. 'apt install ffmpeg' on Debian/Ubuntu).", ex.getMessage());
    }

    @Test void aFilenameSuffixWithPathSeparatorsIsRejected() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> VideoAudioExtractor.extractAudio(new byte[] {1}, "a.b/c"));
        assertTrue(ex.getMessage().startsWith("Invalid video filename"));
    }

    @Test
    @EnabledIf("ffmpegAvailable")
    void extractsMp3AudioFromAVideoWithAnAudioTrack() throws Exception {
        byte[] audio = VideoAudioExtractor.extractAudio(makeVideo(true), "clip.mp4");
        assertTrue(audio.length > 1000, "audio was only " + audio.length + " bytes");
        assertTrue(looksLikeMp3(audio));
    }

    @Test
    @EnabledIf("ffmpegAvailable")
    void aFilenameWithoutADotUsesTheMp4Suffix() throws Exception {
        assertTrue(looksLikeMp3(VideoAudioExtractor.extractAudio(makeVideo(true), "clip")));
    }

    @Test
    @EnabledIf("ffmpegAvailable")
    void aVideoWithoutAnAudioTrackIsRejected() throws Exception {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> VideoAudioExtractor.extractAudio(makeVideo(false), "clip.mp4"));
        assertTrue(ex.getMessage().startsWith("ffmpeg audio extraction failed: "), ex.getMessage());
    }

    @Test
    @EnabledIf("ffmpegAvailable")
    void garbageBytesAreRejected() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> VideoAudioExtractor.extractAudio("this is not a video".getBytes(StandardCharsets.UTF_8), "clip.mp4"));
        assertTrue(ex.getMessage().startsWith("ffmpeg audio extraction failed: "), ex.getMessage());
    }

    @Test
    @EnabledIf("ffmpegAvailable")
    void noTemporaryFilesAreLeftBehind() throws Exception {
        Path root = Path.of(System.getProperty("java.io.tmpdir"));
        long before = countVideoTempDirs(root);
        VideoAudioExtractor.extractAudio(makeVideo(true), "clip.mp4");
        assertThrows(IllegalArgumentException.class, () -> VideoAudioExtractor.extractAudio(new byte[] {1}, "x.mp4"));
        assertEquals(before, countVideoTempDirs(root));
    }

    private static long countVideoTempDirs(Path root) throws IOException {
        try (var s = Files.list(root)) {
            return s.filter(p -> p.getFileName().toString().startsWith("ragleap-video-")).count();
        }
    }
}
