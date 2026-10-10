package com.ragleap.graph;

import java.time.Duration;
import java.util.Objects;

/**
 * Connection settings for the Neo4j HTTP Query API (not a Bolt address).
 * The password is never included in toString().
 */
public record GraphConfig(String baseUrl, String user, String password, String database,
                          Duration connectTimeout, Duration requestTimeout) {
    public GraphConfig {
        Objects.requireNonNull(baseUrl, "baseUrl");
        user = user == null ? "neo4j" : user;
        password = password == null ? "" : password;
        database = database == null || database.isBlank() ? "neo4j" : database;
        connectTimeout = connectTimeout == null ? Duration.ofSeconds(10) : connectTimeout;
        requestTimeout = requestTimeout == null ? Duration.ofSeconds(60) : requestTimeout;
    }

    public GraphConfig(String baseUrl, String user, String password) {
        this(baseUrl, user, password, "neo4j", null, null);
    }

    public GraphConfig() {
        this("http://localhost:7474", "neo4j", "");
    }

    @Override
    public String toString() {
        return "GraphConfig[baseUrl=" + baseUrl + ", user=" + user + ", password=***, database=" + database + "]";
    }
}
