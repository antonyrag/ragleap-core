package com.ragleap.rag.db;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Real integration test against a live Postgres instance - NOT mocked.
 * Connects to a throwaway database (ragleap_java_test), never the
 * production ragleap_core database.
 *
 * Connection URL comes from the RAGLEAP_JAVA_TEST_DATABASE_URL
 * environment variable when set (used in CI), falling back to the
 * VPS's local throwaway database for manual/local runs.
 */
class ConnectionPoolTest {

    private static final String DATABASE_URL = System.getenv().getOrDefault(
            "RAGLEAP_JAVA_TEST_DATABASE_URL",
            "postgresql://ragleap:ragleap@localhost:5433/ragleap_java_test"
    );

    private static ConnectionPool pool;

    @BeforeAll
    static void setUpPool() {
        pool = new ConnectionPool(DATABASE_URL, 1, 5);
    }

    @AfterAll
    static void tearDownPool() {
        pool.close();
    }

    @Test
    void parseDatabaseUrlExtractsCredentialsHostPortAndDatabase() {
        ConnectionPool.ParsedUrl parsed = ConnectionPool.parseDatabaseUrl(
                "postgresql://ragleap:ragleap@localhost:5433/ragleap_java_test");

        assertEquals("jdbc:postgresql://localhost:5433/ragleap_java_test", parsed.jdbcUrl());
        assertEquals("ragleap", parsed.username());
        assertEquals("ragleap", parsed.password());
    }

    @Test
    void parseDatabaseUrlRejectsMissingCredentials() {
        assertThrows(IllegalArgumentException.class,
                () -> ConnectionPool.parseDatabaseUrl("postgresql://localhost:5433/db"));
    }

    @Test
    void getConnectionActuallyConnectsToRealPostgres() throws SQLException {
        try (Connection conn = pool.getConnection()) {
            assertFalse(conn.isClosed());
            assertTrue(conn.isValid(5));
        }
    }

    @Test
    void connectionAutoCommitIsOffMatchingPythonSource() throws SQLException {
        try (Connection conn = pool.getConnection()) {
            assertFalse(conn.getAutoCommit());
        }
    }

    @Test
    void fullRoundTripCreateInsertSelectDropOnRealDatabase() throws SQLException {
        try (Connection conn = pool.getConnection()) {
            try (Statement stmt = conn.createStatement()) {
                stmt.execute("CREATE TABLE IF NOT EXISTS java_port_scratch_test (id SERIAL PRIMARY KEY, val TEXT)");
            }
            conn.commit();

            try (PreparedStatement insert = conn.prepareStatement(
                    "INSERT INTO java_port_scratch_test (val) VALUES (?)")) {
                insert.setString(1, "hello from the java port");
                insert.executeUpdate();
            }
            conn.commit();

            try (Statement select = conn.createStatement();
                 ResultSet rs = select.executeQuery("SELECT val FROM java_port_scratch_test ORDER BY id DESC LIMIT 1")) {
                assertTrue(rs.next());
                assertEquals("hello from the java port", rs.getString("val"));
            }

            try (Statement drop = conn.createStatement()) {
                drop.execute("DROP TABLE java_port_scratch_test");
            }
            conn.commit();
        }
    }

    @Test
    void connectionIsReturnedToPoolNotActuallyClosedByTryWithResources() throws SQLException {
        // Get and release a connection twice in a row - if close() actually
        // closed the underlying socket instead of returning it to the pool,
        // repeated fast acquisition would still work (HikariCP would just
        // open a new one), but this at least proves no exception occurs
        // across repeated get/close cycles, matching the pattern the real
        // service classes (retrieval, memory) will use.
        for (int i = 0; i < 3; i++) {
            try (Connection conn = pool.getConnection()) {
                assertTrue(conn.isValid(5));
            }
        }
    }
}
