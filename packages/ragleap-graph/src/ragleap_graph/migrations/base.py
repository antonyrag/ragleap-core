"""
Migration base class for ragleap-graph's schema migration framework.
See docs/design/schema-migrations.md for the full design rationale.
"""
from abc import ABC, abstractmethod


class Migration(ABC):
    """Base class for a single schema migration step."""

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique, sortable migration identifier.

        Convention: 'NNNN_short_description', e.g. '0001_backfill_user_id'.
        Migrations are applied in lexicographic order of their id.
        """
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this migration does."""
        ...

    @abstractmethod
    def up(self, session) -> dict:
        """Apply the migration forward.

        Args:
            session: An open Neo4j session. The migration owns its own
                     transaction boundaries within this session.

        Returns:
            A dict of migration-specific results (e.g. node counts
            updated). Logged alongside the migration record for
            auditability.

        Raises:
            Any exception - the runner treats all exceptions as hard
            failures and does NOT proceed to the next migration.
        """
        ...

    def down(self, session) -> dict:
        """Reverse the migration (optional).

        Most graph migrations are not safely reversible (you can't
        un-backfill a property without knowing what the "before" state
        was). The default implementation raises NotImplementedError.
        See docs/design/schema-migrations.md Section 7 for the full
        rationale on rollback strategy.
        """
        raise NotImplementedError(
            f"Migration {self.id} does not support down(). "
            f"Restore from a database dump instead - see "
            f"docs/operations/backup-and-restore.md"
        )

    def is_applied(self, session) -> bool:
        """Check whether this migration has already been applied.

        Default implementation checks for a :_Migration node with
        matching id. Override only if the migration needs a different
        idempotency check (e.g. checking whether the property it
        backfills already exists on all target nodes).
        """
        result = session.run(
            "MATCH (m:_Migration {id: $id}) RETURN count(m) > 0 AS applied",
            id=self.id,
        )
        return result.single()["applied"]
