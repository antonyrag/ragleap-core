"""
MigrationRunner for ragleap-graph's schema migration framework.
See docs/design/schema-migrations.md for the full design rationale.
"""
import json
import time
import logging
from typing import List

logger = logging.getLogger(__name__)


class MigrationRunner:
    """Discovers and applies pending migrations in order."""

    def __init__(self, driver, migrations: List):
        """
        Args:
            driver: An active neo4j.Driver instance. Must not be None.
            migrations: All known migrations, in the order they should
                        be applied. The runner sorts by id internally,
                        but passing them pre-sorted is conventional.
        """
        if driver is None:
            raise RuntimeError(
                "MigrationRunner requires an active Neo4j driver. "
                "Cannot run migrations without a database connection."
            )
        self.driver = driver
        self.migrations = sorted(migrations, key=lambda m: m.id)

    def run_pending(self, *, dry_run: bool = False) -> List[dict]:
        """Apply all pending migrations in order.

        Args:
            dry_run: If True, report which migrations would run without
                     actually executing them.

        Returns:
            A list of result dicts, one per migration applied (or that
            would be applied in dry_run mode).

        Raises:
            RuntimeError: If any migration fails. The runner does NOT
                         continue to the next migration after a failure.
                         See docs/design/schema-migrations.md Section 7
                         for recovery guidance.
        """
        if not dry_run:
            logger.warning(
                "About to apply pending schema migrations. Ensure you "
                "have a database dump before proceeding - see "
                "docs/operations/backup-and-restore.md. Migrations are "
                "NOT safe to run concurrently with application writes; "
                "run during a maintenance window."
            )

        results = []

        with self.driver.session() as session:
            for migration in self.migrations:
                if migration.is_applied(session):
                    logger.debug(
                        f"Migration {migration.id} already applied, skipping"
                    )
                    continue

                if dry_run:
                    logger.info(
                        f"[DRY RUN] Would apply: {migration.id} - "
                        f"{migration.description}"
                    )
                    results.append({
                        "id": migration.id,
                        "description": migration.description,
                        "status": "pending",
                    })
                    continue

                logger.info(
                    f"Applying migration: {migration.id} - "
                    f"{migration.description}"
                )
                start_ms = time.monotonic_ns() // 1_000_000

                try:
                    result = migration.up(session)
                except Exception as e:
                    logger.error(
                        f"Migration {migration.id} FAILED: {e}",
                        exc_info=True,
                    )
                    raise RuntimeError(
                        f"Migration {migration.id} failed: {e}. "
                        f"The runner has stopped. No subsequent "
                        f"migrations have been applied. If the graph is "
                        f"in a partial state, restore from a "
                        f"pre-migration dump - see "
                        f"docs/operations/backup-and-restore.md"
                    ) from e

                elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms

                session.run(
                    """
                    CREATE (m:_Migration {
                        id: $id,
                        description: $description,
                        applied_at: datetime(),
                        execution_time_ms: $elapsed_ms,
                        result: $result_json
                    })
                    """,
                    id=migration.id,
                    description=migration.description,
                    elapsed_ms=elapsed_ms,
                    result_json=json.dumps(result, default=str),
                )

                logger.info(
                    f"Migration {migration.id} applied successfully "
                    f"in {elapsed_ms}ms: {result}"
                )
                results.append({
                    "id": migration.id,
                    "description": migration.description,
                    "status": "applied",
                    "elapsed_ms": elapsed_ms,
                    "result": result,
                })

        return results

    def status(self) -> List[dict]:
        """Report the status of all known migrations."""
        statuses = []
        with self.driver.session() as session:
            for migration in self.migrations:
                applied = migration.is_applied(session)
                entry = {
                    "id": migration.id,
                    "description": migration.description,
                    "applied": applied,
                }
                if applied:
                    record = session.run(
                        "MATCH (m:_Migration {id: $id}) "
                        "RETURN m.applied_at AS applied_at, "
                        "       m.execution_time_ms AS elapsed_ms",
                        id=migration.id,
                    ).single()
                    if record:
                        entry["applied_at"] = str(record["applied_at"])
                        entry["elapsed_ms"] = record["elapsed_ms"]
                statuses.append(entry)
        return statuses
