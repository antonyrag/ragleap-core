package com.ragleap.rag.vectorstore;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** A wrong-length embedding must be rejected before anything is stored (found by the failure-mode matrix, issue 565). */
class FaissDimensionValidationTest {

    @Test
    void wrongDimensionInsertIsRejectedAndTheChunkCanBeRetried() throws Exception {
        FaissBackend b = new FaissBackend();
        b.initSchema(4);
        String id = UUID.nameUUIDFromBytes("dimval".getBytes(StandardCharsets.UTF_8)).toString();
        b.insertDocument(id, "d.txt", Map.of());
        SQLException ex = assertThrows(SQLException.class,
                () -> b.insertChunk(id, "d.txt", 0, "t", 1, List.of(1.0, 0.0, 0.0), Map.of()));
        assertEquals("expected 4 dimensions, not 3", ex.getMessage());

        b.insertChunk(id, "d.txt", 0, "t", 1, List.of(1.0, 0.0, 0.0, 0.0), Map.of());
        assertEquals(1, b.searchDense(List.of(1.0, 0.0, 0.0, 0.0), 5, Map.of()).size());
        assertEquals(1L, b.listDocuments(10, 0).get(0).chunkCount());
    }
}
