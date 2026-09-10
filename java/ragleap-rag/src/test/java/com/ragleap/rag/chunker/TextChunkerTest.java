package com.ragleap.rag.chunker;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class TextChunkerTest {

    @Test
    void constructorRejectsOverlapGreaterThanOrEqualToChunkSize() {
        assertThrows(IllegalArgumentException.class, () -> new TextChunker(10, 10));
        assertThrows(IllegalArgumentException.class, () -> new TextChunker(10, 15));
    }

    @Test
    void defaultConstructorUsesStandardDefaults() {
        TextChunker chunker = new TextChunker();
        assertEquals(512, chunker.getChunkSize());
        assertEquals(50, chunker.getChunkOverlap());
    }

    @Test
    void emptyTextReturnsNoChunks() {
        TextChunker chunker = new TextChunker();
        assertTrue(chunker.chunkText("").isEmpty());
        assertTrue(chunker.chunkText("   \n  ").isEmpty());
    }

    @Test
    void nullTextReturnsNoChunks() {
        TextChunker chunker = new TextChunker();
        assertTrue(chunker.chunkText(null).isEmpty());
    }

    @Test
    void chunkCountMatchesSlidingWindowBoundaryCondition() {
        // 25 whitespace tokens, chunkSize=10, overlap=2 -> step=8
        // starts: 0 (end=10), 8 (end=18), 16 (end=25, break) -> 3 chunks
        StringBuilder sb = new StringBuilder();
        for (int i = 1; i <= 25; i++) {
            sb.append("word").append(i).append(" ");
        }
        TextChunker chunker = new TextChunker(10, 2);
        List<Chunk> chunks = chunker.chunkText(sb.toString().trim());

        assertEquals(3, chunks.size());
        assertEquals(0, chunks.get(0).chunkIndex());
        assertEquals("word1 word2 word3 word4 word5 word6 word7 word8 word9 word10",
                chunks.get(0).text());
        assertEquals("word9 word10 word11 word12 word13 word14 word15 word16 word17 word18",
                chunks.get(1).text());
        // last chunk: tokens[16:25] -> word17..word25 (9 tokens, since end==size triggers break)
        assertEquals("word17 word18 word19 word20 word21 word22 word23 word24 word25",
                chunks.get(2).text());
    }

    @Test
    void singleChunkWhenTextShorterThanChunkSize() {
        TextChunker chunker = new TextChunker();
        List<Chunk> chunks = chunker.chunkText("just a few words here");
        assertEquals(1, chunks.size());
        assertEquals("just a few words here", chunks.get(0).text());
    }

    @Test
    void tokenCountIsRealAndMarkedExact() {
        TextChunker chunker = new TextChunker();
        List<Chunk> chunks = chunker.chunkText("The quick brown fox jumps over the lazy dog");
        assertEquals(1, chunks.size());
        Chunk chunk = chunks.get(0);
        assertTrue(chunk.tokenCountIsExact());
        assertTrue(chunk.tokenCount() > 0);
        // cl100k_base tokenizes this classic pangram fragment to more than
        // the 9 whitespace words due to subword splitting — sanity bound only.
        assertTrue(chunk.tokenCount() >= 9);
    }

    @Test
    void factoryMethodsWork() {
        assertNotNull(TextChunker.createChunker());
        TextChunker custom = TextChunker.createChunker(20, 5);
        assertEquals(20, custom.getChunkSize());
        assertEquals(5, custom.getChunkOverlap());
    }
}
