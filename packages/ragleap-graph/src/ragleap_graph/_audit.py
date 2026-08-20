"""
Audit logging for ragleap-graph (v0.6.6+), backed by Postgres.

Fully optional. If GraphIndex is constructed without an AuditConfig (or
with one that has no database_url set), no audit logging occurs and no
psycopg2 import is even attempted - this module has zero effect unless
explicitly configured.

Graceful-degradation philosophy matches the rest of ragleap-graph: if
psycopg2 isn't installed (it's an optional dependency - pip install
ragleap-graph[audit]), if the database_url is unreachable, or if a
write fails for any reason, the real Neo4j operation being audited
still succeeds. Audit logging can fail; the feature it's auditing must
not fail because of it. A warning is logged so the gap is visible, but
nothing raises.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("ragleap_graph.audit")


@dataclass
class AuditConfig:
    """
    Config for audit logging via Postgres. Pass to GraphIndex(audit=...)
    to enable. Requires the `audit` extra: pip install ragleap-graph[audit]

    database_url: standard libpq connection string, e.g.
    "postgresql://user:password@host:5432/dbname". Caller-supplied,
    never hardcoded - self-hosted users bring their own Postgres, the
    same as they bring their own Neo4j instance.
    """
    database_url: Optional[str] = None


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ragleap_graph_audit_log (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id TEXT,
    namespace TEXT,
    action TEXT NOT NULL,
    document_id TEXT,
    entity_count INTEGER,
    detail JSONB
)
"""
_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_ragleap_graph_audit_user_id ON ragleap_graph_audit_log (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_ragleap_graph_audit_namespace ON ragleap_graph_audit_log (namespace)",
    "CREATE INDEX IF NOT EXISTS idx_ragleap_graph_audit_occurred_at ON ragleap_graph_audit_log (occurred_at)",
]
_INSERT_SQL = """
INSERT INTO ragleap_graph_audit_log
    (user_id, namespace, action, document_id, entity_count, detail)
VALUES (%s, %s, %s, %s, %s, %s)
"""


class AuditLogger:
    """
    Holds (and lazily reconnects) a Postgres connection for audit
    logging. Every public method swallows its own errors and logs a
    warning rather than raising - callers never need to guard calls
    into this class with their own try/except.
    """

    def __init__(self, config: Optional[AuditConfig]):
        self.config = config
        self._conn = None
        self._schema_ready = False
        self._warned_no_driver = False

    @property
    def enabled(self) -> bool:
        return bool(self.config and self.config.database_url)

    def _connect(self):
        if self._conn is not None:
            return self._conn
        if not self.enabled:
            return None
        try:
            import psycopg2
        except ImportError:
            if not self._warned_no_driver:
                logger.warning(
                    "AuditConfig.database_url is set but psycopg2 is not "
                    "installed - audit logging is disabled. Install with "
                    "pip install ragleap-graph[audit] to enable it."
                )
                self._warned_no_driver = True
            return None
        try:
            conn = psycopg2.connect(self.config.database_url)
            conn.autocommit = True
            self._conn = conn
            return conn
        except Exception as e:
            logger.warning(f"Audit log connection failed, audit logging disabled for this call: {e}")
            self._conn = None
            return None

    def _ensure_schema(self, conn) -> bool:
        if self._schema_ready:
            return True
        try:
            with conn.cursor() as cur:
                cur.execute(_CREATE_TABLE_SQL)
                for stmt in _CREATE_INDEXES_SQL:
                    cur.execute(stmt)
            self._schema_ready = True
            return True
        except Exception as e:
            logger.warning(f"Audit log schema setup failed, audit logging disabled for this call: {e}")
            return False

    def log(
        self,
        user_id: Optional[str],
        namespace: Optional[str],
        action: str,
        document_id: Optional[str] = None,
        entity_count: Optional[int] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record one audit event. Never raises - any failure (no driver,
        no connection, bad query) is logged as a warning and swallowed,
        so this is always safe to call from inside a real operation
        without a surrounding try/except at the call site.
        """
        if not self.enabled:
            return
        conn = self._connect()
        if conn is None:
            return
        if not self._ensure_schema(conn):
            return
        try:
            import json
            with conn.cursor() as cur:
                cur.execute(
                    _INSERT_SQL,
                    (
                        user_id or None,
                        namespace or None,
                        action,
                        document_id,
                        entity_count,
                        json.dumps(detail) if detail is not None else None,
                    ),
                )
        except Exception as e:
            logger.warning(f"Audit log write failed, continuing without it: {e}")
            self._conn = None

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
