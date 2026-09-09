"""
Schema migration framework for ragleap-graph.

See docs/design/schema-migrations.md for the full design rationale,
and docs/adr/0001-backup-restore-ownership.md for why this framework
does NOT wrap or invoke database backup tooling itself.

Usage:
    from ragleap_graph import GraphIndex, GraphConfig
    from ragleap_graph.migrations import ALL_MIGRATIONS, MigrationRunner

    graph = GraphIndex(config=GraphConfig(...))
    runner = MigrationRunner(graph.driver, ALL_MIGRATIONS)

    # Preview what would run
    pending = runner.run_pending(dry_run=True)

    # Apply (after taking a dump per backup-and-restore.md)
    results = runner.run_pending()
"""
from ragleap_graph.migrations.base import Migration
from ragleap_graph.migrations.runner import MigrationRunner
from ragleap_graph.migrations.registry import (
    Migration0001_BackfillUserIdDefaults,
    Migration0002_BackfillCompositeKey,
    ALL_MIGRATIONS,
)

__all__ = [
    "Migration",
    "MigrationRunner",
    "Migration0001_BackfillUserIdDefaults",
    "Migration0002_BackfillCompositeKey",
    "ALL_MIGRATIONS",
]
