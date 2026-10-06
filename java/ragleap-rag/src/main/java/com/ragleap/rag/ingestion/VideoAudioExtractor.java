package com.ragleap.rag.ingestion;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;

/**
 * Audio extraction from video. Java port of ragleap-rag's video.py (extract_audio_from_video): writes the
 * video to a temp file and runs {@code ffmpeg -y -i <video> -vn -acodec libmp3lame -q:a 2 <out>.mp3}, then
 * returns the MP3 bytes. Same command, same temp-file suffix rule (the filename's last extension, ".mp4" if
 * it has none), same 300 second timeout and same error messages, so the output is byte-for-byte what the
 * Python package produces with the same ffmpeg. Requires the ffmpeg binary on the PATH.
 *
 * <p>Errors that are ValueError in Python throw IllegalArgumentException with the same wording. Not covered:
 * Python decodes ffmpeg's error output strictly and would raise a UnicodeDecodeError on invalid bytes; this
 * class replaces them.
 */
public final class VideoAudioExtractor {

    public static final String DEFAULT_FFMPEG_COMMAND = "ffmpeg";
    static final long TIMEOUT_SECONDS = 300;

    private VideoAudioExtractor() {
    }

    /** Extracts the audio track of the video as MP3 bytes. */
    public static byte[] extractAudio(byte[] rawBytes, String videoFilename) {
        return extractAudio(rawBytes, videoFilename, DEFAULT_FFMPEG_COMMAND);
    }

    /** Same as {@link #extractAudio(byte[], String)} with an explicit ffmpeg command or path. */
    public static byte[] extractAudio(byte[] rawBytes, String videoFilename, String ffmpegCommand) {
        Objects.requireNonNull(rawBytes, "rawBytes");
        Objects.requireNonNull(videoFilename, "videoFilename");
        Objects.requireNonNull(ffmpegCommand, "ffmpegCommand");
        int dot = videoFilename.lastIndexOf('.');
        String suffix = dot >= 0 ? videoFilename.substring(dot) : ".mp4";
        if (suffix.indexOf('/') >= 0 || suffix.indexOf('\\') >= 0 || suffix.indexOf('\0') >= 0) {
            throw new IllegalArgumentException("Invalid video filename: " + videoFilename);
        }
        Path dir = null;
        try {
            dir = Files.createTempDirectory("ragleap-video-");
            Path video = dir.resolve("video" + suffix);
            Files.write(video, rawBytes);
            Path audio = dir.resolve("video" + suffix + ".mp3");
            Path log = dir.resolve("ffmpeg.log");
            ProcessBuilder pb = new ProcessBuilder(List.of(ffmpegCommand, "-y", "-i", video.toString(),
                    "-vn", "-acodec", "libmp3lame", "-q:a", "2", audio.toString()));
            pb.redirectOutput(ProcessBuilder.Redirect.DISCARD);
            pb.redirectError(log.toFile());
            Process proc;
            try {
                proc = pb.start();
            } catch (IOException e) {
                throw new IllegalArgumentException("ffmpeg is required for video ingestion but is not installed on this system. "
                        + "Install it (e.g. 'apt install ffmpeg' on Debian/Ubuntu).", e);
            }
            proc.getOutputStream().close();
            boolean finished;
            try {
                finished = proc.waitFor(TIMEOUT_SECONDS, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                proc.destroyForcibly();
                Thread.currentThread().interrupt();
                throw new IllegalArgumentException("Interrupted while waiting for ffmpeg", e);
            }
            if (!finished) {
                proc.destroyForcibly();
                throw new IllegalArgumentException("ffmpeg audio extraction timed out (video may be too long or corrupt).");
            }
            if (proc.exitValue() != 0) {
                throw new IllegalArgumentException("ffmpeg audio extraction failed: " + tail(log, 500));
            }
            if (!Files.exists(audio) || Files.size(audio) == 0) {
                throw new IllegalArgumentException("ffmpeg produced no audio output — the video may have no audio track.");
            }
            return Files.readAllBytes(audio);
        } catch (IOException e) {
            throw new IllegalArgumentException("Could not run ffmpeg: " + e.getMessage(), e);
        } finally {
            deleteQuietly(dir);
        }
    }

    /** The last {@code n} characters of the log, like Python's stderr[-500:] (not stripped). */
    private static String tail(Path log, int n) {
        try {
            String s = new String(Files.readAllBytes(log), StandardCharsets.UTF_8);
            return s.length() <= n ? s : s.substring(s.length() - n);
        } catch (IOException e) {
            return "";
        }
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
