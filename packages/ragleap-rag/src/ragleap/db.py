"""
Shared connection pooling for ragleap-rag.
Every service class (retrieval, memory) shares one pool instead of
opening a new psycopg2 connection per call — a fresh TCP handshake +
Postgres auth on every single method call is a real, avoidable latency
cost, especially under any concurrent load.
"""
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Thin wrapper around psycopg2's ThreadedConnectionPool."""

    def __init__(self, database_url: str, min_conn: int = 1, max_conn: int = 10):
        import psycopg2.pool
        self.database_url = database_url
        self._pool = psycopg2.pool.ThreadedConnectionPool(min_conn, max_conn, database_url)
        logger.info(f"Connection pool created (min={min_conn}, max={max_conn})")

    @contextmanager
    def get_connection(self):
        """
        Usage: with pool.get_connection() as conn: ...
        Connection is always returned to the pool afterward, even on
        error. Caller is responsible for conn.commit()/rollback() as
        needed — the pool does not auto-commit.
        """
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def close(self):
        """Close all connections in the pool. Call on shutdown if needed."""
        self._pool.closeall()
        logger.info("Connection pool closed")
