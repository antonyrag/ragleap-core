package com.ragleap.vectorstores;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ragleap.rag.vectorstore.DocumentSummary;
import com.ragleap.rag.vectorstore.SearchResult;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;

/**
 * Live check against a real Redis Stack (RediSearch). Skipped unless RAGLEAP_VS_LIVE_REDIS_URL is set (for example
 * redis://127.0.0.1:6381/0 for a throwaway container; RediSearch only indexes database 0). Uses its own index and key
 * prefix and drops them at the end. Never point it at a production Redis.
 */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_VS_LIVE_REDIS_URL", matches = ".+")
class RedisLiveTest {

    private static List<SearchResult> searchUntil(RedisBackend be, Map<String, Object> filter, int expected) throws Exception {
        List<SearchResult> r = List.of();
        for (int i = 0; i < 50; i++) {
            r = be.searchDense(List.of(1.0, 0.0, 0.0), 10, filter);
            if (r.size() >= expected) {
                return r;
            }
            Thread.sleep(100);
        }
        return r;
    }

    @Test
    void liveRoundTrip(@TempDir Path tmp) throws Exception {
        String url = System.getenv("RAGLEAP_VS_LIVE_REDIS_URL");
        String sfx = UUID.randomUUID().toString().substring(0, 8);
        String index = "live_idx_" + sfx;
        try (RedisBackend be = new RedisBackend(url, index, "live:" + sfx + ":", tmp.resolve("r.sqlite3").toString())) {
            try {
                be.initSchema(3);
                be.initSchema(3);   // the index exists now: it is reused
                be.insertDocument("d1", "a.txt", Map.of("k", "v"));
                be.insertDocument("doc-2:x", "b.txt", Map.of());
                be.insertChunk("d1", "a.txt", 0, "alpha", 1, List.of(1.0, 0.0, 0.0), Map.of());
                be.insertChunk("d1", "a.txt", 1, "beta", 1, List.of(0.0, 1.0, 0.0), Map.of());
                be.insertChunk("d1", "a.txt", 2, "gamma", 1, List.of(-1.0, 0.0, 0.0), Map.of());
                be.insertChunk("doc-2:x", "b.txt", 0, "delta", 1, List.of(0.9, 0.1, 0.0), Map.of());

                List<SearchResult> all = searchUntil(be, null, 4);
                StringBuilder sb = new StringBuilder();
                for (SearchResult s : all) {
                    sb.append(s.text()).append('=').append(s.similarityScore()).append(' ');
                }
                System.out.println("LIVE redis scores (query [1,0,0]): " + sb);
                System.out.println("LIVE redis first chunk id: " + (all.isEmpty() ? "none" : all.get(0).chunkId()));

                assertEquals(4, all.size());
                assertEquals(List.of("alpha", "delta", "beta", "gamma"), all.stream().map(SearchResult::text).toList());
                assertTrue(all.get(0).similarityScore() > 0.99, "identical vector should score about 1");
                assertEquals(1.0, all.get(0).similarityScore(), 0.0005);
                assertEquals(0.997, all.get(1).similarityScore(), 0.001);
                assertEquals(0.5, all.get(2).similarityScore(), 0.0005);
                assertEquals(0.0, all.get(3).similarityScore(), 0.0005);
                assertEquals("doc-2:x", all.get(1).documentId());
                assertEquals(0, all.get(1).chunkIndex());

                List<SearchResult> d1 = searchUntil(be, Map.of("document_id", "d1"), 3);
                assertEquals(3, d1.size());
                List<SearchResult> hyphen = searchUntil(be, Map.of("document_id", "doc-2:x"), 1);
                assertEquals(List.of("delta"), hyphen.stream().map(SearchResult::text).toList());
                List<SearchResult> ignored = be.searchDense(List.of(1.0, 0.0, 0.0), 10, Map.of("other", "ignored"));
                assertEquals(4, ignored.size(), "unsupported filter keys are ignored, not applied");

                List<DocumentSummary> docs = be.listDocuments(10, 0);
                Map<String, Long> counts = new java.util.HashMap<>();
                for (DocumentSummary d : docs) {
                    counts.put(d.documentId(), d.chunkCount());
                }
                System.out.println("LIVE redis chunk counts: " + counts);
                assertEquals(3L, counts.get("d1"));
                assertEquals(1L, counts.get("doc-2:x"));

                assertTrue(be.deleteDocument("d1"));
                List<SearchResult> after = List.of();
                for (int i = 0; i < 50; i++) {
                    after = be.searchDense(List.of(1.0, 0.0, 0.0), 10, null);
                    if (after.size() == 1) {
                        break;
                    }
                    Thread.sleep(100);
                }
                assertEquals(List.of("delta"), after.stream().map(SearchResult::text).toList());
                assertTrue(be.getDocumentFilename("d1").isEmpty());
            } finally {
                try (RespClient c = new RespClient(url)) {
                    c.command("FT.DROPINDEX", index, "DD");
                } catch (Exception e) {
                    System.out.println("LIVE redis cleanup warning: " + e.getMessage());
                }
            }
        }
    }
}
