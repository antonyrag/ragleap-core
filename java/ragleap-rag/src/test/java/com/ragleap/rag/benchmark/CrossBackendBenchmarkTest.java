package com.ragleap.rag.benchmark;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
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
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Cross-backend retrieval benchmark (issue #565). Every backend receives identical, precomputed
 * vectors (see java/ragleap-rag/benchmark/prepare_dataset.py). Ground truth is an exact float64
 * cosine scan computed here, so no backend is trusted as its own reference.
 *
 * Skipped unless RAGLEAP_BENCH_DIR points at a folder containing corpus.json. Choose backends with
 * RAGLEAP_BENCH_BACKENDS (comma list of faiss, pgvector, qdrant, weaviate; default faiss). One JSON
 * result file per backend is written to RAGLEAP_BENCH_OUT (default RAGLEAP_BENCH_DIR/results).
 *
 * Metrics: overlap@10 (share of the exact top-10 returned), top-1 agreement, gold hit@1/5/10
 * (does the backend find the paragraph the question was written from), score range, deviation of
 * the returned score from (cosine+1)/2, and indicative latency. At this corpus size the HNSW
 * indexes of Qdrant and Weaviate behave like exact search, so this does not measure approximate
 * recall at scale.
 */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_BENCH_DIR", matches = ".+")
class CrossBackendBenchmarkTest {

    private static final int TOP_K = 10;
    private static final Map<String, Object> NO_FILTER = Map.of();
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String QDRANT_URL = "http://localhost:6333";
    private static final String WEAVIATE_URL = "http://localhost:8081";
    private static final String PG_URL = System.getenv().getOrDefault("RAGLEAP_BENCH_PG_URL",
            "postgresql://ragleap:ragleap@localhost:5433/ragleap_java_bench");
    private static final String PG_JDBC = System.getenv().getOrDefault("RAGLEAP_BENCH_PG_JDBC",
            "jdbc:postgresql://localhost:5433/ragleap_java_bench");

    private record Doc(String id, String title, String text, List<Double> vec) {
    }

    private record Query(String id, String text, String gold, List<Double> vec) {
    }

    /** Exact ranking per query, plus exact cosine of every document. */
    private record Truth(List<List<String>> top, List<Map<String, Double>> sim) {
    }

    @TempDir
    Path tempDir;

    @Test
    void runBenchmark() throws Exception {
        Path dir = Path.of(System.getenv("RAGLEAP_BENCH_DIR"));
        Path outDir = Path.of(System.getenv().getOrDefault("RAGLEAP_BENCH_OUT", dir.resolve("results").toString()));
        Files.createDirectories(outDir);
        JsonNode root = MAPPER.readTree(dir.resolve("corpus.json").toFile());
        int dim = root.get("dim").asInt();
        List<Doc> docs = new ArrayList<>();
        for (JsonNode d : root.get("docs")) {
            docs.add(new Doc(uid(d.get("id").asText()), d.get("title").asText(), d.get("text").asText(), toList(d.get("vec"))));
        }
        List<Query> queries = new ArrayList<>();
        for (JsonNode q : root.get("queries")) {
            queries.add(new Query(q.get("id").asText(), q.get("text").asText(), uid(q.get("gold").asText()), toList(q.get("vec"))));
        }
        Truth truth = computeTruth(docs, queries);
        writeJson(outDir.resolve("exact-float64.json"), referenceResult(docs, queries, truth, dim));

        List<String> names = Arrays.stream(System.getenv().getOrDefault("RAGLEAP_BENCH_BACKENDS", "faiss").split(","))
                .map(String::trim).filter(s -> !s.isEmpty()).toList();
        List<String> failures = new ArrayList<>();
        for (String name : names) {
            try {
                ObjectNode r = runBackend(name, docs, queries, truth, dim);
                writeJson(outDir.resolve(name + ".json"), r);
                System.out.println(summaryLine(r));
            } catch (Throwable t) {
                failures.add(name + ": " + t);
                ObjectNode err = MAPPER.createObjectNode();
                err.put("backend", name);
                err.put("error", String.valueOf(t));
                writeJson(outDir.resolve(name + ".json"), err);
                t.printStackTrace(System.out);
            }
        }
        assertTrue(failures.isEmpty(), "Backends failed: " + failures);
    }

    // ------------------------------------------------------------------ ground truth

    private static Truth computeTruth(List<Doc> docs, List<Query> queries) {
        List<List<String>> top = new ArrayList<>();
        List<Map<String, Double>> sims = new ArrayList<>();
        for (Query q : queries) {
            Map<String, Double> sim = new HashMap<>();
            for (Doc d : docs) {
                sim.put(d.id(), cosine(q.vec(), d.vec()));
            }
            List<String> ids = new ArrayList<>(sim.keySet());
            ids.sort((a, b) -> Double.compare(sim.get(b), sim.get(a)));
            top.add(ids);
            sims.add(sim);
        }
        return new Truth(top, sims);
    }

    private static double cosine(List<Double> a, List<Double> b) {
        double dot = 0;
        double na = 0;
        double nb = 0;
        for (int i = 0; i < a.size(); i++) {
            double x = a.get(i);
            double y = b.get(i);
            dot += x * y;
            na += x * x;
            nb += y * y;
        }
        return dot / (Math.sqrt(na) * Math.sqrt(nb));
    }

    private static ObjectNode referenceResult(List<Doc> docs, List<Query> queries, Truth truth, int dim) {
        int[] hit = new int[3];
        for (int qi = 0; qi < queries.size(); qi++) {
            addGoldHits(hit, truth.top().get(qi), queries.get(qi).gold());
        }
        ObjectNode r = MAPPER.createObjectNode();
        r.put("backend", "exact-float64");
        r.put("docs", docs.size());
        r.put("queries", queries.size());
        r.put("dim", dim);
        r.put("goldHit1", hit[0] / (double) queries.size());
        r.put("goldHit5", hit[1] / (double) queries.size());
        r.put("goldHit10", hit[2] / (double) queries.size());
        return r;
    }

    private static void addGoldHits(int[] hit, List<String> ranked, String gold) {
        int rank = ranked.indexOf(gold);
        if (rank >= 0) {
            if (rank < 1) {
                hit[0]++;
            }
            if (rank < 5) {
                hit[1]++;
            }
            if (rank < 10) {
                hit[2]++;
            }
        }
    }

    // ------------------------------------------------------------------ one backend

    private ObjectNode runBackend(String name, List<Doc> docs, List<Query> queries, Truth truth, int dim) throws Exception {
        String runId = Long.toString(System.currentTimeMillis());
        VectorBackend backend = create(name, runId);
        try {
            backend.initSchema(dim);
            long t0 = System.nanoTime();
            for (Doc d : docs) {
                backend.insertDocument(d.id(), d.title(), Map.of("source", "squad"));
                backend.insertChunk(d.id(), d.title(), 0, d.text(), d.text().trim().split("\\s+").length,
                        d.vec(), Map.of("source", "squad"));
            }
            double insertMs = (System.nanoTime() - t0) / 1e6;
            assertEquals(docs.size(), backend.listDocuments(1000, 0).size(), name + ": not every document was stored");

            backend.searchDense(queries.get(0).vec(), TOP_K, NO_FILTER); // warm-up, not counted

            double overlapSum = 0;
            int top1 = 0;
            int[] hit = new int[3];
            double devSum = 0;
            double devMax = 0;
            long devN = 0;
            int unknownIds = 0;
            double sMin = Double.MAX_VALUE;
            double sMax = -Double.MAX_VALUE;
            int minReturned = Integer.MAX_VALUE;
            List<Double> latency = new ArrayList<>();
            for (int qi = 0; qi < queries.size(); qi++) {
                Query q = queries.get(qi);
                long s = System.nanoTime();
                List<SearchResult> res = backend.searchDense(q.vec(), TOP_K, NO_FILTER);
                latency.add((System.nanoTime() - s) / 1e6);
                List<String> got = new ArrayList<>();
                for (SearchResult r : res) {
                    got.add(r.documentId());
                }
                minReturned = Math.min(minReturned, got.size());
                Set<String> exactTop = new HashSet<>(truth.top().get(qi).subList(0, TOP_K));
                int common = 0;
                for (String g : got) {
                    if (exactTop.contains(g)) {
                        common++;
                    }
                }
                overlapSum += common / (double) TOP_K;
                if (!got.isEmpty() && got.get(0).equals(truth.top().get(qi).get(0))) {
                    top1++;
                }
                addGoldHits(hit, got, q.gold());
                for (SearchResult r : res) {
                    double score = r.similarityScore();
                    sMin = Math.min(sMin, score);
                    sMax = Math.max(sMax, score);
                    Double cos = truth.sim().get(qi).get(r.documentId());
                    if (cos == null) {
                        unknownIds++;
                        continue;
                    }
                    double dev = Math.abs(score - (cos + 1) / 2);
                    devSum += dev;
                    devMax = Math.max(devMax, dev);
                    devN++;
                }
            }
            Collections.sort(latency);
            int n = queries.size();
            ObjectNode r = MAPPER.createObjectNode();
            r.put("backend", name);
            r.put("docs", docs.size());
            r.put("queries", n);
            r.put("dim", dim);
            r.put("topK", TOP_K);
            r.put("minResultsReturned", minReturned);
            r.put("overlapAt10", overlapSum / n);
            r.put("top1Agreement", top1 / (double) n);
            r.put("goldHit1", hit[0] / (double) n);
            r.put("goldHit5", hit[1] / (double) n);
            r.put("goldHit10", hit[2] / (double) n);
            r.put("scoreMin", sMin);
            r.put("scoreMax", sMax);
            r.put("scoresInUnitInterval", sMin >= -1e-9 && sMax <= 1 + 1e-9);
            r.put("scoreDevMean", devN == 0 ? Double.NaN : devSum / devN);
            r.put("scoreDevMax", devMax);
            r.put("unknownIdsReturned", unknownIds);
            r.put("latencyMedianMs", latency.get(n / 2));
            r.put("latencyP95Ms", latency.get((int) Math.ceil(0.95 * n) - 1));
            r.put("insertTotalMs", insertMs);
            return r;
        } finally {
            closeQuietly(backend);
            cleanup(name, runId);
        }
    }

    private VectorBackend create(String name, String runId) throws Exception {
        return switch (name) {
            case "faiss" -> new FaissBackend();
            case "pgvector" -> new PgVectorBackend(PG_URL, 0.0);
            case "qdrant" -> new QdrantBackend(tempDir.resolve("qd").toString(), QDRANT_URL, null, "bench_" + runId);
            case "weaviate" -> new WeaviateBackend(tempDir.resolve("wv").toString(), WEAVIATE_URL, null, "Bench" + runId);
            default -> throw new IllegalArgumentException("Unknown backend: " + name);
        };
    }

    private static void closeQuietly(VectorBackend backend) {
        if (backend instanceof AutoCloseable c) {
            try {
                c.close();
            } catch (Exception e) {
                System.out.println("close warning: " + e);
            }
        }
    }

    private static void cleanup(String name, String runId) {
        try {
            switch (name) {
                case "qdrant" -> httpDelete(QDRANT_URL + "/collections/bench_" + runId);
                case "weaviate" -> httpDelete(WEAVIATE_URL + "/v1/schema/Bench" + runId);
                case "pgvector" -> {
                    try (Connection c = DriverManager.getConnection(PG_JDBC, "ragleap", "ragleap");
                         Statement st = c.createStatement()) {
                        st.execute("DROP TABLE IF EXISTS chunks CASCADE");
                        st.execute("DROP TABLE IF EXISTS documents CASCADE");
                    }
                }
                default -> {
                }
            }
        } catch (Exception e) {
            System.out.println("cleanup warning (" + name + "): " + e);
        }
    }

    private static void httpDelete(String url) throws Exception {
        HttpClient.newHttpClient().send(HttpRequest.newBuilder().uri(URI.create(url)).DELETE().build(),
                HttpResponse.BodyHandlers.discarding());
    }

    // ------------------------------------------------------------------ helpers

    /** pgvector stores document ids as UUIDs, so every backend gets deterministic UUID ids. */
    private static String uid(String raw) {
        return java.util.UUID.nameUUIDFromBytes(("bench:" + raw).getBytes(java.nio.charset.StandardCharsets.UTF_8)).toString();
    }

    private static List<Double> toList(JsonNode arr) {
        List<Double> out = new ArrayList<>(arr.size());
        for (JsonNode n : arr) {
            out.add(n.asDouble());
        }
        return out;
    }

    private static void writeJson(Path file, ObjectNode node) throws Exception {
        MAPPER.writerWithDefaultPrettyPrinter().writeValue(file.toFile(), node);
    }

    private static String summaryLine(ObjectNode r) {
        return String.format(Locale.ROOT,
                "BENCH %-9s overlap@10=%.3f top1=%.3f gold@1=%.3f gold@5=%.3f gold@10=%.3f "
                        + "scoreDev(mean/max)=%.5f/%.5f score[%.3f..%.3f] unit=%s p50=%.1fms p95=%.1fms insert=%.0fms",
                r.get("backend").asText(), r.get("overlapAt10").asDouble(), r.get("top1Agreement").asDouble(),
                r.get("goldHit1").asDouble(), r.get("goldHit5").asDouble(), r.get("goldHit10").asDouble(),
                r.get("scoreDevMean").asDouble(), r.get("scoreDevMax").asDouble(),
                r.get("scoreMin").asDouble(), r.get("scoreMax").asDouble(), r.get("scoresInUnitInterval").asBoolean(),
                r.get("latencyMedianMs").asDouble(), r.get("latencyP95Ms").asDouble(), r.get("insertTotalMs").asDouble());
    }
}
