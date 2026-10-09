package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.Test;

class PureLogicTest {
    @Test
    void normalizeEmptyAndShort() {
        assertEquals("", EntityExtraction.normalizeEntityName(""));
        assertEquals("", EntityExtraction.normalizeEntityName(null));
        assertEquals("", EntityExtraction.normalizeEntityName("ab"));
    }

    @Test
    void normalizeCollapsesWhitespaceAndStripsPunctuation() {
        assertEquals("Acme Corp Inc", EntityExtraction.normalizeEntityName("Acme   Corp\n\tInc"));
        assertEquals("Acme Corp", EntityExtraction.normalizeEntityName("  (Acme Corp).  "));
    }

    @Test
    void normalizeAcronymsAndTitleCase() {
        assertEquals("ALARA", EntityExtraction.normalizeEntityName("ALARA"));
        assertEquals("IAEA", EntityExtraction.normalizeEntityName("IAEA"));
        assertEquals("Acme Corp", EntityExtraction.normalizeEntityName("acme corp"));
        assertEquals("Acme Corp", EntityExtraction.normalizeEntityName("ACME corp"));
    }

    @Test
    void normalizeTruncatesLongNames() {
        assertEquals(120, EntityExtraction.normalizeEntityName("A".repeat(200)).length());
    }

    @Test
    void extractFindsAcronymsAndPhrases() {
        assertTrue(EntityExtraction.extractEntityCandidates("The IAEA published new guidelines.").contains("IAEA"));
        List<String> r = EntityExtraction.extractEntityCandidates("Acme Corp signed a deal with Globex Industries.");
        assertTrue(r.contains("Acme Corp"));
        assertTrue(r.contains("Globex Industries"));
    }

    @Test
    void extractDropsSentenceInitialStopwords() {
        List<String> r = EntityExtraction.extractQueryEntities("What did Acme Corp launch?");
        assertTrue(r.contains("Acme Corp"));
        assertFalse(r.contains("What"));
    }

    @Test
    void extractDeduplicatesAndRespectsMax() {
        List<String> r = EntityExtraction.extractEntityCandidates("Acme Corp is great. Acme Corp is really great.");
        assertEquals(1, r.stream().filter("Acme Corp"::equals).count());
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 20; i++) {
            sb.append("Company").append(i).append(" Corp ");
        }
        assertTrue(EntityExtraction.extractEntityCandidates(sb.toString(), 5, null).size() <= 5);
    }

    @Test
    void domainTermsAreOptional() {
        String text = "we discussed radiation safety protocols today";
        assertTrue(EntityExtraction.extractEntityCandidates(text).stream().noneMatch(e -> e.toLowerCase().contains("radiation")));
        assertTrue(EntityExtraction.extractEntityCandidates(text, 12, List.of("radiation safety")).contains("Radiation Safety"));
    }

    @Test
    void compositeKeyMatchesKnownSha256Vectors() {
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", CompositeKey.of());
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", CompositeKey.of("abc"));
    }
}
