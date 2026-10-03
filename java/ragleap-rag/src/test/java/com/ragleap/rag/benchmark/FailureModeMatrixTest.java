package com.ragleap.rag.benchmark;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ragleap.rag.vectorstore.FaissBackend;
import com.ragleap.rag.vectorstore.PgVectorBackend;
import com.ragleap.rag.vectorstore.QdrantBackend;
import com.ragleap.rag.vectorstore.SearchResult;
import com.ragleap.rag.vectorstore.VectorBackend;
import com.ragleap.rag.vectorstore.WeaviateBackend;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import static org.junit.jupiter.api.Assertions.assertFalse;

/**
 * Failure-mode matrix (issue #565): runs the same edge cases against every live backend and RECORDS
 * what happens (result or exception type) without asserting, so differences between backends show up.
 * Skipped unless RAGLEAP_BENCH_DIR is set. Backends: RAGLEAP_BENCH_BACKENDS (faiss, pgvector, qdrant,
 * weaviate). Output: RAGLEAP_BENCH_OUT/failure-matrix.json plus "MATRIX" lines on stdout.
 */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_BENCH_DIR", matches = ".+")
class FailureModeMatrixTest {

    private static final String QDRANT_URL = "http://localhost:6333";
    private static final String WEAVIATE_URL = "http://localhost:8081";
    private static final String PG_URL = System.getenv().getOrDefault("RAGLEAP_BENCH_PG_URL",
            "postgresql://ragleap:ragleap@localhost:5433/ragleap_java_bench");
    private static final String PG_JDBC = System.getenv().getOrDefault("RAGLEAP_BENCH_PG_JDBC",
            "jdbc:postgresql://localhost:5433/ragleap_java_bench");
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private interface Step {
        void run() throws Exception;
    }

    private interface Check {
        String run(VectorBackend b, String backendName, Path dir) throws Exception;
    }

    private record Case(String id, String description, Check check, int timeoutSec, boolean ownBackend) {
    }

    @TempDir
    Path tempDir;

    private VectorBackend pgShared;

    // ------------------------------------------------------------------ helpers

    private static List<Double> vec(double... v) {
        return Arrays.stream(v).boxed().toList();
    }

    private static String uid(String raw) {
        return UUID.nameUUIDFromBytes(("matrix:" + raw).getBytes(StandardCharsets.UTF_8)).toString();
    }

    private static String describe(Throwable t) {
        if (t == null) {
            return "unknown";
        }
        String m = String.valueOf(t.getMessage()).replace('\n', ' ').replace('\r', ' ');
        if (m.length() > 110) {
            m = m.substring(0, 110) + "...";
        }
        return t.getClass().getSimpleName() + ": " + m;
    }

    private static String attempt(Step s) {
        try {
            s.run();
            return "ok";
        } catch (Throwable t) {
            return "EXC " + describe(t);
        }
    }

    private static void fresh(VectorBackend b) throws Exception {
        b.initSchema(4);
    }

    private static void seed(VectorBackend b) throws Exception {
        fresh(b);
        String[] names = {"A", "B", "C"};
        double[][] vs = {{1, 0, 0, 0}, {0, 1, 0, 0}, {1, 1, 0, 0}};
        for (int i = 0; i < 3; i++) {
            String id = uid(names[i]);
            b.insertDocument(id, names[i] + ".txt", Map.of("k", "v"));
            b.insertChunk(id, names[i] + ".txt", 0, "text " + names[i], 2, vec(vs[i]), Map.of("k", "v"));
        }
    }

    private static final List<Double> Q = vec(1, 0, 0, 0);

    // ------------------------------------------------------------------ the cases

    private static List<Case> cases() {
        List<Case> c = new ArrayList<>();
        c.add(new Case("empty-collection-search", "search before any data is stored", (b, n, d) -> {
            fresh(b);
            return b.searchDense(Q, 5, Map.of()).size() + " results";
        }, 60, false));
        c.add(new Case("topk-larger-than-data", "topK=100 with 3 chunks stored", (b, n, d) -> {
            seed(b);
            return b.searchDense(Q, 100, Map.of()).size() + " results";
        }, 60, false));
        c.add(new Case("filter-matches-nothing", "metadata filter k=nope (nothing has it)", (b, n, d) -> {
            seed(b);
            return b.searchDense(Q, 5, Map.of("k", "nope")).size() + " results";
        }, 60, false));
        c.add(new Case("filter-matches-all", "metadata filter k=v (every chunk has it)", (b, n, d) -> {
            seed(b);
            return b.searchDense(Q, 5, Map.of("k", "v")).size() + " results";
        }, 60, false));
        c.add(new Case("delete-missing-document", "deleteDocument for an id that was never stored", (b, n, d) -> {
            seed(b);
            return "returned " + b.deleteDocument(uid("never-stored"));
        }, 60, false));
        c.add(new Case("filename-of-missing-document", "getDocumentFilename for an unknown id", (b, n, d) -> {
            seed(b);
            return "present=" + b.getDocumentFilename(uid("never-stored")).isPresent();
        }, 60, false));
        c.add(new Case("duplicate-insert", "same document and same chunk index inserted twice", (b, n, d) -> {
            fresh(b);
            String id = uid("dup");
            String d1 = attempt(() -> b.insertDocument(id, "dup.txt", Map.of("k", "v")));
            String d2 = attempt(() -> b.insertDocument(id, "dup.txt", Map.of("k", "v")));
            String c1 = attempt(() -> b.insertChunk(id, "dup.txt", 0, "t", 1, vec(1, 0, 0, 0), Map.of("k", "v")));
            String c2 = attempt(() -> b.insertChunk(id, "dup.txt", 0, "t", 1, vec(1, 0, 0, 0), Map.of("k", "v")));
            int docs = b.listDocuments(100, 0).size();
            int hits = b.searchDense(Q, 10, Map.of()).size();
            return "doc#1=" + d1 + ", doc#2=" + d2 + ", chunk#1=" + c1 + ", chunk#2=" + c2 + ", documents=" + docs + ", hits=" + hits;
        }, 60, false));
        c.add(new Case("wrong-dimension-insert", "insert a 3-dim vector into a 4-dim collection", (b, n, d) -> {
            fresh(b);
            String id = uid("wd");
            b.insertDocument(id, "wd.txt", Map.of());
            b.insertChunk(id, "wd.txt", 0, "t", 1, vec(1, 0, 0), Map.of());
            return "accepted; hits=" + b.searchDense(Q, 5, Map.of()).size();
        }, 60, false));
        c.add(new Case("wrong-dimension-query", "search with a 3-dim query against 4-dim data", (b, n, d) -> {
            seed(b);
            return b.searchDense(vec(1, 0, 0), 5, Map.of()).size() + " results";
        }, 60, false));
        c.add(new Case("zero-vector", "insert an all-zero embedding, then search", (b, n, d) -> {
            fresh(b);
            String id = uid("zero");
            b.insertDocument(id, "zero.txt", Map.of());
            b.insertChunk(id, "zero.txt", 0, "t", 1, vec(0, 0, 0, 0), Map.of());
            List<SearchResult> r = b.searchDense(Q, 5, Map.of());
            return "hits=" + r.size() + (r.isEmpty() ? "" : ", score=" + r.get(0).similarityScore());
        }, 60, false));
        c.add(new Case("unicode-and-quotes", "unicode, quotes, backslash and newline in filename, metadata and text", (b, n, d) -> {
            fresh(b);
            String id = uid("uni");
            String name = "\u6587\u6863-\u00e9-\uD83D\uDE00 \"q\".txt";
            String val = "\u65e5\u672c \"quote\" 'single' \\ back";
            String text = "h\u00e9llo \u65e5\u672c\nline2 \"q\" \uD83D\uDE00";
            b.insertDocument(id, name, Map.of("k", val));
            b.insertChunk(id, name, 0, text, 3, vec(1, 0, 0, 0), Map.of("k", val));
            boolean nameOk = name.equals(b.getDocumentFilename(id).orElse(null));
            List<SearchResult> all = b.searchDense(Q, 5, Map.of());
            boolean textOk = all.size() == 1 && text.equals(all.get(0).text());
            String filtered;
            try {
                filtered = String.valueOf(b.searchDense(Q, 5, Map.of("k", val)).size());
            } catch (Throwable t) {
                filtered = "EXC " + describe(t);
            }
            return "filename roundtrip=" + nameOk + ", text roundtrip=" + textOk + ", filter on that value -> " + filtered + " hit(s)";
        }, 60, false));
        c.add(new Case("init-schema-twice", "initSchema called a second time", (b, n, d) -> {
            fresh(b);
            return "second call: " + attempt(() -> b.initSchema(4));
        }, 60, false));
        c.add(new Case("pagination", "listDocuments(limit 2, offset 0) and (limit 2, offset 2) with 3 documents", (b, n, d) -> {
            seed(b);
            return b.listDocuments(2, 0).size() + " then " + b.listDocuments(2, 2).size();
        }, 60, false));
        c.add(new Case("delete-then-search", "delete document A, then search", (b, n, d) -> {
            seed(b);
            boolean deleted = b.deleteDocument(uid("A"));
            List<SearchResult> r = b.searchDense(Q, 10, Map.of());
            boolean stillThere = r.stream().anyMatch(x -> "A.txt".equals(x.documentName()));
            return "deleted=" + deleted + ", hits=" + r.size() + ", deleted doc still returned=" + stillThere;
        }, 60, false));
        c.add(new Case("score-identical-vs-opposite", "scores of an identical and an opposite vector", (b, n, d) -> {
            fresh(b);
            String p = uid("pos");
            String q = uid("neg");
            b.insertDocument(p, "pos", Map.of());
            b.insertChunk(p, "pos", 0, "t", 1, vec(1, 0, 0, 0), Map.of());
            b.insertDocument(q, "neg", Map.of());
            b.insertChunk(q, "neg", 0, "t", 1, vec(-1, 0, 0, 0), Map.of());
            Map<String, Double> s = new HashMap<>();
            for (SearchResult r : b.searchDense(Q, 5, Map.of())) {
                s.put(r.documentName(), r.similarityScore());
            }
            return String.format(Locale.ROOT, "identical=%.4f, opposite=%.4f", s.get("pos"), s.get("neg"));
        }, 60, false));
        c.add(new Case("filter-on-unknown-key", "metadata filter on a key that no chunk has (nokey=x)", (b, n, d) -> {
            seed(b);
            return b.searchDense(Q, 5, Map.of("nokey", "x")).size() + " results";
        }, 60, false));
        c.add(new Case("failed-insert-then-retry", "insert with a wrong-dimension vector (fails), then retry the same chunk correctly", (b, n, d) -> {
            fresh(b);
            String id = uid("retry");
            b.insertDocument(id, "retry.txt", Map.of("k", "v"));
            String bad = attempt(() -> b.insertChunk(id, "retry.txt", 0, "t", 1, vec(1, 0, 0), Map.of("k", "v")));
            String retry = attempt(() -> b.insertChunk(id, "retry.txt", 0, "t", 1, vec(1, 0, 0, 0), Map.of("k", "v")));
            String search;
            try {
                search = b.searchDense(Q, 5, Map.of()).size() + " hit(s)";
            } catch (Throwable t) {
                search = "EXC " + describe(t);
            }
            long chunks = b.listDocuments(10, 0).stream().mapToLong(x -> x.chunkCount()).sum();
            return "wrong-dim insert=" + bad + ", retry=" + retry + ", search=" + search + ", chunks listed=" + chunks;
        }, 60, false));
        c.add(new Case("search-after-deleting-everything", "delete all three documents, then search and list", (b, n, d) -> {
            seed(b);
            for (String nm : new String[] {"A", "B", "C"}) {
                b.deleteDocument(uid(nm));
            }
            return b.searchDense(Q, 5, Map.of()).size() + " results, documents listed=" + b.listDocuments(10, 0).size();
        }, 60, false));
        c.add(new Case("server-unreachable", "backend pointed at a port with nothing listening", (b, n, d) -> {
            switch (n) {
                case "pgvector" -> {
                    VectorBackend bad = new PgVectorBackend("postgresql://ragleap:ragleap@localhost:1/none", 0.0);
                    bad.initSchema(4);
                    return "no error raised";
                }
                case "qdrant" -> {
                    VectorBackend bad = new QdrantBackend(d.toString(), "http://localhost:1", null, "x");
                    bad.initSchema(4);
                    return "no error raised";
                }
                case "weaviate" -> {
                    VectorBackend bad = new WeaviateBackend(d.toString(), "http://localhost:1", null, "X");
                    bad.initSchema(4);
                    return "no error raised";
                }
                default -> {
                    return "N/A (in-process, no server)";
                }
            }
        }, 25, true));
        return c;
    }

    // ------------------------------------------------------------------ running

    @Test
    void recordFailureModes() throws Exception {
        Path dir = Path.of(System.getenv("RAGLEAP_BENCH_DIR"));
        Path outDir = Path.of(System.getenv().getOrDefault("RAGLEAP_BENCH_OUT", dir.resolve("results").toString()));
        Files.createDirectories(outDir);
        List<String> names = Arrays.stream(System.getenv().getOrDefault("RAGLEAP_BENCH_BACKENDS", "faiss").split(","))
                .map(String::trim).filter(s -> !s.isEmpty()).toList();
        String runId = Long.toString(System.currentTimeMillis());
        List<Case> cases = cases();

        ObjectNode root = MAPPER.createObjectNode();
        ArrayNode arr = root.putArray("cases");
        for (int i = 0; i < cases.size(); i++) {
            Case c = cases.get(i);
            ObjectNode node = arr.addObject();
            node.put("id", c.id());
            node.put("description", c.description());
            ObjectNode results = node.putObject("results");
            for (String name : names) {
                String outcome = runCase(c, name, runId + "x" + i, i);
                results.put(name, outcome);
                System.out.println("MATRIX " + String.format("%-30s", c.id()) + " " + String.format("%-9s", name) + " " + outcome);
            }
        }
        MAPPER.writerWithDefaultPrettyPrinter().writeValue(outDir.resolve("failure-matrix.json").toFile(), root);
        dropPgTables();
        assertFalse(cases.isEmpty());
    }

    private String runCase(Case c, String name, String key, int idx) {
        ExecutorService ex = Executors.newSingleThreadExecutor();
        VectorBackend backend = null;
        try {
            if (!c.ownBackend()) {
                backend = open(name, key, idx);
            }
            final VectorBackend b = backend;
            final Path caseDir = tempDir.resolve("c" + idx + name);
            Future<String> f = ex.submit(() -> c.check().run(b, name, caseDir));
            try {
                String r = f.get(c.timeoutSec(), TimeUnit.SECONDS);
                return r.startsWith("N/A") ? r : "OK " + r;
            } catch (TimeoutException t) {
                f.cancel(true);
                return "TIMEOUT after " + c.timeoutSec() + "s";
            } catch (ExecutionException e) {
                return "EXC " + describe(e.getCause());
            }
        } catch (Throwable t) {
            return "SETUP EXC " + describe(t);
        } finally {
            ex.shutdownNow();
            if (backend instanceof AutoCloseable ac && backend != pgShared) {
                try {
                    ac.close();
                } catch (Exception ignored) {
                    // best effort
                }
            }
            cleanup(name, key);
        }
    }

    private VectorBackend open(String name, String key, int idx) throws Exception {
        return switch (name) {
            case "faiss" -> new FaissBackend();
            case "pgvector" -> {
                if (pgShared == null) {
                    pgShared = new PgVectorBackend(PG_URL, 0.0);
                }
                yield pgShared;
            }
            case "qdrant" -> new QdrantBackend(tempDir.resolve("qd" + key).toString(), QDRANT_URL, null, "matrix_" + key);
            case "weaviate" -> new WeaviateBackend(tempDir.resolve("wv" + key).toString(), WEAVIATE_URL, null, "Matrix" + key);
            default -> throw new IllegalArgumentException("Unknown backend: " + name);
        };
    }

    private void cleanup(String name, String key) {
        try {
            switch (name) {
                case "qdrant" -> httpDelete(QDRANT_URL + "/collections/matrix_" + key);
                case "weaviate" -> httpDelete(WEAVIATE_URL + "/v1/schema/Matrix" + key);
                case "pgvector" -> dropPgTables();
                default -> {
                }
            }
        } catch (Exception e) {
            System.out.println("cleanup warning (" + name + "): " + e);
        }
    }

    private static void dropPgTables() {
        try (Connection c = DriverManager.getConnection(PG_JDBC, "ragleap", "ragleap"); Statement st = c.createStatement()) {
            st.execute("DROP TABLE IF EXISTS chunks CASCADE");
            st.execute("DROP TABLE IF EXISTS documents CASCADE");
        } catch (Exception e) {
            System.out.println("cleanup warning (pgvector tables): " + e);
        }
    }

    private static void httpDelete(String url) throws Exception {
        HttpClient.newHttpClient().send(HttpRequest.newBuilder().uri(URI.create(url)).DELETE().build(),
                HttpResponse.BodyHandlers.discarding());
    }
}
