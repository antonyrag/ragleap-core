package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class QueryApiRunnerTest {
    private HttpServer server;
    private volatile String lastBody;
    private volatile String lastAuth;
    private volatile String lastPath;
    private volatile int status = 200;
    private volatile String responseBody = "{}";

    @BeforeEach
    void start() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", ex -> {
            lastBody = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            lastAuth = ex.getRequestHeaders().getFirst("Authorization");
            lastPath = ex.getRequestURI().getPath();
            byte[] out = responseBody.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json");
            ex.sendResponseHeaders(status, out.length == 0 ? -1 : out.length);
            if (out.length > 0) {
                try (OutputStream os = ex.getResponseBody()) {
                    os.write(out);
                }
            }
            ex.close();
        });
        server.start();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    private QueryApiRunner runner() {
        return new QueryApiRunner(new GraphConfig("http://127.0.0.1:" + server.getAddress().getPort(), "neo4j", "pw"));
    }

    @Test
    void mapsRowsAndValueTypes() {
        responseBody = "{\"data\":{\"fields\":[\"i\",\"f\",\"s\",\"n\",\"l\",\"m\"],"
                + "\"values\":[[1,2.0,\"x\",null,[1,\"a\"],{\"k\":1}]]}}";
        List<Map<String, Object>> rows = runner().run("RETURN 1", Map.of());
        assertEquals(1, rows.size());
        Map<String, Object> row = rows.get(0);
        assertEquals(1L, row.get("i"));
        assertEquals(2.0, row.get("f"));
        assertTrue(row.get("f") instanceof Double);
        assertEquals("x", row.get("s"));
        assertNull(row.get("n"));
        assertEquals(List.of(1L, "a"), row.get("l"));
        assertEquals(Map.of("k", 1L), row.get("m"));
    }

    @Test
    void sendsDoublesWithDecimalPointAndIntegersWithout() {
        responseBody = "{\"data\":{\"fields\":[],\"values\":[]}}";
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("w", 1.0);
        params.put("n", 1);
        params.put("big", 9007199254740993L);
        params.put("s", "h\u00e9llo");
        runner().run("RETURN $w", params);
        assertTrue(lastBody.contains("\"w\":1.0"), lastBody);
        assertTrue(lastBody.contains("\"n\":1,") || lastBody.contains("\"n\":1}"), lastBody);
        assertTrue(lastBody.contains("\"big\":9007199254740993"), lastBody);
        assertTrue(lastBody.contains("\"s\":\"h\u00e9llo\""), lastBody);
    }

    @Test
    void sendsBasicAuthAndUsesTheQueryApiPath() {
        responseBody = "{\"data\":{\"fields\":[],\"values\":[]}}";
        runner().run("RETURN 1", Map.of());
        String expected = "Basic " + Base64.getEncoder().encodeToString("neo4j:pw".getBytes(StandardCharsets.UTF_8));
        assertEquals(expected, lastAuth);
        assertEquals("/db/neo4j/query/v2", lastPath);
    }

    @Test
    void mapsTransientAndClientErrors() {
        status = 409;
        responseBody = "{\"errors\":[{\"code\":\"Neo.TransientError.Transaction.DeadlockDetected\",\"message\":\"deadlock\"}]}";
        GraphException transientError = assertThrows(GraphTransientException.class, () -> runner().run("X", Map.of()));
        assertTrue(transientError.getMessage().contains("DeadlockDetected"));
        status = 400;
        responseBody = "{\"errors\":[{\"code\":\"Neo.ClientError.Statement.SyntaxError\",\"message\":\"bad\"}]}";
        GraphException clientError = assertThrows(GraphException.class, () -> runner().run("X", Map.of()));
        assertFalse(clientError instanceof GraphTransientException);
        assertTrue(clientError.getMessage().contains("SyntaxError"));
    }

    @Test
    void httpErrorWithoutBodyIsReported() {
        status = 401;
        responseBody = "";
        GraphException e = assertThrows(GraphException.class, () -> runner().run("X", Map.of()));
        assertTrue(e.getMessage().contains("401"));
    }

    @Test
    void connectionFailureIsAGraphException() {
        QueryApiRunner dead = new QueryApiRunner(new GraphConfig("http://127.0.0.1:1", "x", "x"));
        assertThrows(GraphException.class, () -> dead.run("RETURN 1", Map.of()));
    }

    @Test
    void rejectsNonFiniteNumbers() {
        assertThrows(IllegalArgumentException.class, () -> runner().run("X", Map.of("w", Double.NaN)));
    }

    @Test
    void passwordIsNotPrintedByToString() {
        String text = new GraphConfig("http://h:7474", "u", "secret-password").toString();
        assertFalse(text.contains("secret-password"));
    }
}
