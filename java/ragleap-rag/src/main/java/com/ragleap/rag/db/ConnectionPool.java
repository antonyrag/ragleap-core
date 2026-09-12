package com.ragleap.rag.db;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

import java.net.URI;
import java.net.URISyntaxException;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.logging.Logger;

/**
 * Shared connection pooling for ragleap-rag. Java port of ragleap-rag's
 * db.py — ConnectionPool.
 *
 * Every service class (retrieval, memory) shares one pool instead of
 * opening a new connection per call — a fresh TCP handshake + Postgres
 * auth on every single method call is a real, avoidable latency cost,
 * especially under any concurrent load.
 *
 * Uses HikariCP - the Java equivalent of psycopg2's ThreadedConnectionPool.
 *
 * Usage maps directly onto the Python source's context-manager pattern:
 *   try (Connection conn = pool.getConnection()) {
 *       ...
 *       conn.commit(); // or conn.rollback() - autoCommit is off, matching
 *                       // "the pool does not auto-commit" in the Python docstring
 *   }
 * try-with-resources calling Connection.close() is HikariCP's equivalent
 * of psycopg2's putconn() - it returns the connection to the pool rather
 * than actually closing the underlying socket, and runs even on
 * exception, same as Python's try/finally.
 */
public class ConnectionPool implements AutoCloseable {

    private static final Logger logger = Logger.getLogger(ConnectionPool.class.getName());

    public static final int DEFAULT_MIN_CONN = 1;
    public static final int DEFAULT_MAX_CONN = 10;

    private final HikariDataSource dataSource;

    public ConnectionPool(String databaseUrl) {
        this(databaseUrl, DEFAULT_MIN_CONN, DEFAULT_MAX_CONN);
    }

    public ConnectionPool(String databaseUrl, int minConn, int maxConn) {
        ParsedUrl parsed = parseDatabaseUrl(databaseUrl);

        HikariConfig config = new HikariConfig();
        config.setJdbcUrl(parsed.jdbcUrl());
        config.setUsername(parsed.username());
        config.setPassword(parsed.password());
        config.setMinimumIdle(minConn);
        config.setMaximumPoolSize(maxConn);
        // Caller is responsible for commit()/rollback(), matching the
        // Python source's documented "the pool does not auto-commit".
        config.setAutoCommit(false);

        this.dataSource = new HikariDataSource(config);
        logger.info(() -> String.format("Connection pool created (min=%d, max=%d)", minConn, maxConn));
    }

    /**
     * Get a connection from the pool. Use in try-with-resources -
     * closing it returns the connection to the pool, it does not close
     * the underlying socket. See class javadoc for the Python
     * context-manager equivalence.
     */
    public Connection getConnection() throws SQLException {
        return dataSource.getConnection();
    }

    /** Close all connections in the pool. Call on shutdown if needed. */
    @Override
    public void close() {
        dataSource.close();
        logger.info("Connection pool closed");
    }

    record ParsedUrl(String jdbcUrl, String username, String password) {
    }

    /**
     * Parses a postgresql://user:pass@host:port/dbname URL (psycopg2's
     * accepted format) into a JDBC URL plus separate username/password,
     * since the JDBC PostgreSQL driver doesn't accept credentials
     * embedded in the URL the way psycopg2 does.
     */
    static ParsedUrl parseDatabaseUrl(String databaseUrl) {
        URI uri;
        try {
            uri = new URI(databaseUrl);
        } catch (URISyntaxException e) {
            throw new IllegalArgumentException("Invalid database URL: " + databaseUrl, e);
        }

        String userInfo = uri.getUserInfo();
        if (userInfo == null) {
            throw new IllegalArgumentException("Database URL must include user:password - got: " + databaseUrl);
        }
        String[] credentials = userInfo.split(":", 2);
        String username = credentials[0];
        String password = credentials.length > 1 ? credentials[1] : "";

        String host = uri.getHost();
        int port = uri.getPort();
        String database = uri.getPath();
        if (database != null && database.startsWith("/")) {
            database = database.substring(1);
        }

        String jdbcUrl = String.format("jdbc:postgresql://%s:%d/%s", host, port, database);
        return new ParsedUrl(jdbcUrl, username, password);
    }
}
