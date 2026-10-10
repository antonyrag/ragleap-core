package com.ragleap.graph;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * CypherRunner over the Neo4j HTTP Query API v2 (POST /db/{database}/query/v2).
 * Every call is its own auto-commit transaction. Doubles are sent as JSON numbers
 * with a decimal point, which Neo4j stores as FLOAT; integers are sent without one.
 * Single server only: result bookmarks are not passed along.
 */
public final class QueryApiRunner implements CypherRunner {
    private static final ObjectMapper MAPPER =
            new ObjectMapper().configure(DeserializationFeature.USE_LONG_FOR_INTS, true);

    private final HttpClient client;
    private final URI endpoint;
    private final String authHeader;
    private final Duration requestTimeout;

    public QueryApiRunner(GraphConfig config) {
        String base = config.baseUrl().replaceAll("/+$", "");
        String db = URLEncoder.encode(config.database(), StandardCharsets.UTF_8).replace("+", "%20");
        this.endpoint = URI.create(base + "/db/" + db + "/query/v2");
        String credentials = config.user() + ":" + config.password();
        this.authHeader = "Basic " + Base64.getEncoder().encodeToString(credentials.getBytes(StandardCharsets.UTF_8));
        this.requestTimeout = config.requestTimeout();
        this.client = HttpClient.newBuilder().connectTimeout(config.connectTimeout()).build();
    }

    @Override
    public List<Map<String, Object>> run(String cypher, Map<String, Object> params) {
        Map<String, Object> safeParams = params == null ? Map.of() : params;
        checkFinite(safeParams);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("statement", cypher);
        payload.put("parameters", safeParams);
        String body;
        try {
            body = MAPPER.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new GraphException("Could not encode query parameters: " + e.getMessage(), e);
        }
        HttpRequest request = HttpRequest.newBuilder(endpoint)
                .timeout(requestTimeout)
                .header("Content-Type", "application/json")
                .header("Accept", "application/json")
                .header("Authorization", authHeader)
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                .build();
        HttpResponse<String> response;
        try {
            response = client.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new GraphException("Request to Neo4j failed: " + e.getMessage(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new GraphException("Request to Neo4j was interrupted", e);
        }
        return parse(response.statusCode(), response.body());
    }

    @Override
    public void close() {
        client.close();
    }

    private static List<Map<String, Object>> parse(int status, String text) {
        JsonNode root;
        try {
            root = MAPPER.readTree(text == null ? "" : text);
        } catch (JsonProcessingException e) {
            throw new GraphException("Unexpected response from Neo4j (HTTP " + status + ")");
        }
        JsonNode errors = root.path("errors");
        if (errors.isArray() && errors.size() > 0) {
            String code = errors.get(0).path("code").asText("");
            String message = errors.get(0).path("message").asText("");
            String full = code.isEmpty() ? message : code + ": " + message;
            if (code.startsWith("Neo.TransientError.")) {
                throw new GraphTransientException(full);
            }
            throw new GraphException(full);
        }
        if (status < 200 || status >= 300) {
            throw new GraphException("Neo4j returned HTTP " + status);
        }
        JsonNode data = root.path("data");
        JsonNode fields = data.path("fields");
        List<Map<String, Object>> rows = new ArrayList<>();
        for (JsonNode values : data.path("values")) {
            Map<String, Object> row = new LinkedHashMap<>();
            for (int i = 0; i < fields.size(); i++) {
                row.put(fields.get(i).asText(), convert(values.get(i)));
            }
            rows.add(row);
        }
        return rows;
    }

    private static Object convert(JsonNode n) {
        if (n == null || n.isNull() || n.isMissingNode()) {
            return null;
        }
        if (n.isTextual()) {
            return n.textValue();
        }
        if (n.isBoolean()) {
            return n.booleanValue();
        }
        if (n.isIntegralNumber()) {
            return n.canConvertToLong() ? (Object) n.longValue() : n.bigIntegerValue();
        }
        if (n.isNumber()) {
            return n.doubleValue();
        }
        if (n.isArray()) {
            List<Object> list = new ArrayList<>();
            for (JsonNode e : n) {
                list.add(convert(e));
            }
            return list;
        }
        Map<String, Object> map = new LinkedHashMap<>();
        n.fields().forEachRemaining(e -> map.put(e.getKey(), convert(e.getValue())));
        return map;
    }

    private static void checkFinite(Object value) {
        if (value instanceof Double d && (d.isNaN() || d.isInfinite())) {
            throw new IllegalArgumentException("Non-finite number in query parameters");
        }
        if (value instanceof Float f && (f.isNaN() || f.isInfinite())) {
            throw new IllegalArgumentException("Non-finite number in query parameters");
        }
        if (value instanceof Map<?, ?> m) {
            for (Object v : m.values()) {
                checkFinite(v);
            }
        } else if (value instanceof Collection<?> c) {
            for (Object v : c) {
                checkFinite(v);
            }
        }
    }
}
