"""
Concrete migrations for ragleap-graph.
See docs/design/schema-migrations.md for the full design rationale.
"""
from ragleap_graph.migrations.base import Migration
from ragleap_graph import (
    _backfill_user_id_defaults_session,
    _backfill_composite_key_session,
)


class Migration0001_BackfillUserIdDefaults(Migration):
    """Backfill user_id='' onto pre-v0.6.5 nodes missing the property."""

    @property
    def id(self) -> str:
        return "0001_backfill_user_id"

    @property
    def description(self) -> str:
        return (
            "Backfill user_id='' onto Entity/Document/PairWeight/"
            "RelationWeight nodes written before v0.6.5 user_id= "
            "support. Without this, legacy nodes are invisible to "
            "find_* queries and silently duplicated on re-upsert."
        )

    def up(self, session) -> dict:
        return _backfill_user_id_defaults_session(session, namespace=None)


class Migration0002_BackfillCompositeKey(Migration):
    """Backfill composite_key onto pre-v0.6.7 nodes for concurrency safety."""

    @property
    def id(self) -> str:
        return "0002_backfill_composite_key"

    @property
    def description(self) -> str:
        return (
            "Backfill composite_key (SHA256 hash of identity fields) "
            "onto nodes written before v0.6.7. Required for the "
            "single-property uniqueness constraints that close the "
            "concurrent-duplicate race (issue #183)."
        )

    def up(self, session) -> dict:
        return _backfill_composite_key_session(session, namespace=None)


ALL_MIGRATIONS = [
    Migration0001_BackfillUserIdDefaults(),
    Migration0002_BackfillCompositeKey(),
]
