package com.ragleap.rag.parsers;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Compares DocumentParser with the real Python parsers.py on fixture files that a
 * Python script generated (file X, plus X.expected holding Python's exact output, or
 * X.error holding its error message). Set RAGLEAP_PARITY_DIR to the fixture folder to
 * run it; without it the test is skipped, so CI does not need Python or any fixtures.
 */
class PythonParityFixturesTest {

    /** Python raised a library exception (not a ValueError) whose text cannot be reproduced; only "an error was raised" is compared. */
    private static final Set<String> MESSAGE_MAY_DIFFER = Set.of("xls_garbage.xls");

    private static String esc(String s) {
        return "'" + s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\u000B", "\\v") + "'";
    }

    @Test
    void matchesRealPythonOutputOnEveryFixture() throws IOException {
        String dir = System.getenv("RAGLEAP_PARITY_DIR");
        Assumptions.assumeTrue(dir != null && !dir.isBlank(), "RAGLEAP_PARITY_DIR not set - skipping Python parity check");
        List<Path> files;
        try (Stream<Path> s = Files.list(Path.of(dir))) {
            files = s.sorted().toList();
        }
        List<String> failures = new ArrayList<>();
        int checked = 0;
        int skipped = 0;
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
            if (!DocumentParser.SUPPORTED_EXTENSIONS.contains(DocumentParser.extensionOf(name))) {
                skipped++;
                continue;
            }
            checked++;
            byte[] raw = Files.readAllBytes(file);
            try {
                String got = DocumentParser.extractText(name, raw);
                if (!Files.exists(expected)) {
                    failures.add(name + ": Python raised an error but Java returned " + esc(got));
                } else {
                    String want = Files.readString(expected, StandardCharsets.UTF_8);
                    if (!want.equals(got)) {
                        failures.add(name + ":\n   python = " + esc(want) + "\n   java   = " + esc(got));
                    }
                }
            } catch (IllegalArgumentException e) {
                if (Files.exists(error)) {
                    String want = Files.readString(error, StandardCharsets.UTF_8);
                    if (!want.equals(e.getMessage()) && !MESSAGE_MAY_DIFFER.contains(name)) {
                        failures.add(name + ": error message differs:\n   python = " + esc(want) + "\n   java   = " + esc(e.getMessage()));
                    }
                } else {
                    failures.add(name + ": Java raised " + esc(String.valueOf(e.getMessage())) + " but Python returned text");
                }
            }
        }
        System.out.println("PARITY: checked=" + checked + " skipped(not yet ported)=" + skipped + " failures=" + failures.size());
        assertTrue(checked > 0, "no fixtures were checked");
        assertTrue(failures.isEmpty(), "Differences from real Python output:\n" + String.join("\n", failures));
    }
}
