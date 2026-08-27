# Schema Migrations — Design Proposal for ragleap-graph

> **Status: Proposal.**
> This document proposes a lightweight migration framework for
> `ragleap-graph`'s Neo4j schema. It is a design artifact for maintainer
> review, not an implemented feature. No code changes are required to
> ship this document.

---

## 1. Problem statement

`ragleap-graph` has two existing bespoke migrations:

1. **`backfill_user_id_defaults()`** (v0.6.5) — backfills `user_id=""`
   onto nodes written before `user_id=` support existed.
2. **`backfill_composite_key()`** (v0.6.7) — backfills `composite_key`
   onto nodes written before the concurrency fix (issue #183).

Both are idempotent, manually invoked methods on `GraphIndex`. Neither
tracks whether it has already been run — callers must know to run them,
and re-running is harmless but wasteful. There is **no** migration
runner, version table, or schema-tracking mechanism anywhere in the
codebase (confirmed by searching for `_Migration`, `schema_version`,
`migration_runner`, and similar patterns across all source files).

As the schema evolves, each new migration requires a new bespoke method
on `GraphIndex`, its own idempotency logic, its own documentation, and
its own test coverage — all duplicated patterns. This proposal
standardizes the pattern so a future contributor can add a migration in
under 20 lines.

---

## 2. Proposed `Migration` interface

```python
from abc import ABC, abstractmethod
from neo4j import Session
from datetime import datetime
from typing import Optional


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
    def up(self, session: Session) -> dict:
        """Apply the migration forward.

        Args:
            session: An open Neo4j session. The migration owns its own
                     transaction boundaries within this session.

        Returns:
            A dict of migration-specific results (e.g. node counts updated).
            This is logged alongside the migration record for auditability.

        Raises:
            Any exception — the runner treats all exceptions as hard
            failures and does NOT proceed to the next migration.
        """
        ...

    def down(self, session: Session) -> dict:
        """Reverse the migration (optional).

        Most graph migrations are not safely reversible (you can't
        un-backfill a property without knowing what the "before" state
        was). The default implementation raises NotImplementedError.
        See Section 7 for the full rationale on rollback strategy.
        """
        raise NotImplementedError(
            f"Migration {self.id} does not support down(). "
            f"Restore from a database dump instead — see "
            f"docs/operations/backup-and-restore.md"
        )

    def is_applied(self, session: Session) -> bool:
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
```

### Design notes

- **Neo4j `Session` as the boundary**, not `Transaction`. Each migration
  manages its own transaction boundaries because some migrations need
  multiple read-then-write passes (e.g. `backfill_composite_key()`
  reads all nodes, computes keys in Python, then writes back in batches).
  A single Neo4j transaction spanning all of that would hold locks for
  too long and risk deadlocks under concurrent access.

- **`id` is a string, not an integer.** String IDs (`0001_...`,
  `0002_...`) are lexicographically sortable and more descriptive in
  logs and the graph itself. This matches the convention used by Django
  migrations, Alembic, and similar frameworks.

- **`down()` is optional and defaults to `NotImplementedError`.** This
  is a deliberate design choice — see Section 7 for the full rationale.

---

## 3. Migration state tracking

Migration state is tracked **inside the Neo4j graph itself**, using
`:_Migration` nodes:

```cypher
CREATE (m:_Migration {
    id: "0001_backfill_user_id",
    description: "Backfill user_id='' onto pre-v0.6.5 nodes",
    applied_at: datetime(),
    execution_time_ms: 1234,
    result: '{"Entity": 42, "Document": 10, ...}'
})
```

### Why in-graph, not an external file or table?

| Option | Pros | Cons |
|--------|------|------|
| **`:_Migration` node in Neo4j** | Co-located with the data it describes; survives dump/restore round-trips; no additional infrastructure | Couples migration tracking to Neo4j availability |
| **External file (e.g. `.migrations.json`)** | No Neo4j dependency for tracking | Can desync from the actual database state; not included in dump/restore |
| **Postgres table** | Already available (audit log uses Postgres) | Forces a hard Postgres dependency for graph-only users; cross-database consistency problem |

**Recommendation: `:_Migration` node.** The key advantage is that
dump/restore (per `backup-and-restore.md`) preserves migration state
automatically — if you restore a pre-migration dump, the `:_Migration`
nodes are gone too, so the runner correctly re-applies them.

### Schema for `:_Migration` nodes

| Property           | Type       | Description                                        |
|--------------------|------------|----------------------------------------------------|
| `id`               | `String`   | Migration identifier, matches `Migration.id`       |
| `description`      | `String`   | Human-readable description                         |
| `applied_at`       | `DateTime` | When the migration was applied (Neo4j `datetime()`) |
| `execution_time_ms`| `Integer`  | Wall-clock time to execute `up()`                   |
| `result`           | `String`   | JSON-serialized return value of `up()`              |

The `:_Migration` label is prefixed with `_` to signal it's internal
infrastructure, consistent with `ragleap-graph`'s convention of treating
`_`-prefixed names as non-public (see `VERSIONING.md`).

---

## 4. `MigrationRunner` architecture

```python
import json
import time
import logging
from typing import List

logger = logging.getLogger(__name__)


class MigrationRunner:
    """Discovers and applies pending migrations in order."""

    def __init__(self, driver, migrations: List[Migration]):
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
                         See Section 7 for recovery guidance.
        """
        results = []

        with self.driver.session() as session:
            for migration in self.migrations:
                if migration.is_applied(session):
                    logger.debug(f"Migration {migration.id} already applied, skipping")
                    continue

                if dry_run:
                    logger.info(f"[DRY RUN] Would apply: {migration.id} — {migration.description}")
                    results.append({
                        "id": migration.id,
                        "description": migration.description,
                        "status": "pending",
                    })
                    continue

                logger.info(f"Applying migration: {migration.id} — {migration.description}")
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
                        f"The runner has stopped. No subsequent migrations "
                        f"have been applied. If the graph is in a partial "
                        f"state, restore from a pre-migration dump — see "
                        f"docs/operations/backup-and-restore.md"
                    ) from e

                elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms

                # Record the migration as applied
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
```

### Key design decisions

1. **Fail-loud, fail-fast.** If a migration raises, the runner stops
   immediately and raises `RuntimeError` with clear guidance. It does
   **not** silently skip, swallow the error, or continue to the next
   migration. This matches `ragleap-graph`'s existing philosophy — see
   how `GraphIndex.__init__` calls `verify_connectivity()` eagerly
   rather than failing silently on first use.

2. **No automatic backup trigger.** The runner does not call
   `neo4j-admin dump` or any backup tooling. It can't — `neo4j-admin`
   requires filesystem access and typically database shutdown, which a
   Python library running through the Bolt protocol cannot orchestrate.
   Instead, the error message explicitly points operators to
   `backup-and-restore.md`.

   > [!IMPORTANT]
   > **Open question for maintainers:** Should `run_pending()` log a
   > prominent `WARNING` at the start reminding operators to dump first,
   > or is the documentation reference in the error message sufficient?
   > A warning-on-start is cheap insurance but could become noise for
   > operators who always dump first.

3. **`dry_run` mode.** Lets operators preview what would run before
   committing. Low implementation cost, high operational value.

4. **Single-session execution.** All migrations run within one driver
   session (not one transaction — each migration manages its own
   transaction boundaries). This keeps the runner simple while giving
   migrations full control over batching.

---

## 5. Worked example: refactoring `backfill_user_id_defaults()`

This shows what the existing `backfill_user_id_defaults()` (v0.6.5)
**would look like** as a registered migration. This is a **design
illustration, not a refactoring PR** — the existing method would
continue to work as-is alongside the migration framework during a
transition period.

```python
class Migration0001_BackfillUserIdDefaults(Migration):
    """Backfill user_id='' onto pre-v0.6.5 nodes missing the property."""

    @property
    def id(self) -> str:
        return "0001_backfill_user_id"

    @property
    def description(self) -> str:
        return (
            "Backfill user_id='' onto Entity/Document/PairWeight/"
            "RelationWeight nodes written before v0.6.5 user_id= support. "
            "Without this, legacy nodes are invisible to find_* queries "
            "and silently duplicated on re-upsert."
        )

    def up(self, session) -> dict:
        counts = {}
        for label in ["Entity", "Document", "PairWeight", "RelationWeight"]:
            result = session.run(
                f"""
                MATCH (n:{label})
                WHERE n.user_id IS NULL
                SET n.user_id = ""
                RETURN count(n) AS updated
                """,
            )
            record = result.single()
            counts[label] = record["updated"] if record else 0
        return counts

    # down() intentionally not implemented:
    # Removing user_id from nodes that had it set to "" would break
    # every query path that filters on coalesce(user_id, '') — the
    # nodes would become invisible again, which is the exact bug this
    # migration fixes. Restoring from a dump is the safe rollback path.
```

And the second existing migration:

```python
class Migration0002_BackfillCompositeKey(Migration):
    """Backfill composite_key onto pre-v0.6.7 nodes for concurrency safety."""

    @property
    def id(self) -> str:
        return "0002_backfill_composite_key"

    @property
    def description(self) -> str:
        return (
            "Backfill composite_key (SHA256 hash of identity fields) onto "
            "nodes written before v0.6.7. Required for the single-property "
            "uniqueness constraints that close the concurrent-duplicate "
            "race (issue #183)."
        )

    def up(self, session) -> dict:
        # This would reuse the same logic as the current
        # backfill_composite_key() method — read nodes missing
        # composite_key, compute keys in Python via _composite_key(),
        # write back in batches via elementId().
        #
        # The full implementation is identical to the existing method
        # body at __init__.py L1304-L1403, just with `self` references
        # replaced by direct session usage and _composite_key() import.
        #
        # Not duplicated here to keep this design doc honest about what
        # it is (a proposal, not a refactoring PR).
        raise NotImplementedError("Worked example — see __init__.py L1304-L1403")

    # down() intentionally not implemented:
    # Removing composite_key would leave nodes outside the uniqueness
    # constraint, re-exposing the concurrency bug (issue #183).
```

### Registration

```python
# In a future ragleap_graph/migrations/__init__.py (or similar)

ALL_MIGRATIONS = [
    Migration0001_BackfillUserIdDefaults(),
    Migration0002_BackfillCompositeKey(),
]
```

### Usage

```python
from ragleap_graph import GraphIndex, GraphConfig
from ragleap_graph.migrations import ALL_MIGRATIONS, MigrationRunner

graph = GraphIndex(config=GraphConfig(...))
runner = MigrationRunner(graph.driver, ALL_MIGRATIONS)

# Preview what would run
pending = runner.run_pending(dry_run=True)
print(f"{len(pending)} migrations pending")

# Apply (after taking a dump per backup-and-restore.md)
results = runner.run_pending()
```

---

## 6. Concurrency assumptions

> [!WARNING]
> **Migrations are NOT safe to run concurrently with application writes.**
> Run migrations during a maintenance window with `upsert_document()`
> traffic stopped. See issue #183 for the broader concurrency context.

Specific concerns:

1. **`backfill_user_id_defaults()`** writes `SET n.user_id = ""` to nodes
   where `user_id IS NULL`. A concurrent `upsert_document()` could race
   to create a new node without `user_id` between the migration's read
   and write, leaving that node un-backfilled. Since the migration is
   idempotent, re-running it after the write window closes is safe — but
   the operator must know to do so.

2. **`backfill_composite_key()`** reads all nodes missing `composite_key`,
   computes keys in Python, and writes them back in batches. A concurrent
   write creating a new node without `composite_key` between read and
   write would be missed. The same re-run solution applies.

3. **The `MigrationRunner` itself** is not re-entrant. Two runners
   executing concurrently could both see the same migration as "not
   applied" and both attempt to run it. Since migrations are idempotent,
   this is wasteful but not corrupting — however, both would create
   `:_Migration` tracking nodes, leaving duplicates. A future
   enhancement could add a uniqueness constraint on `:_Migration.id` to
   prevent this, but it's not worth the complexity until there's a real
   multi-instance deployment pattern that would trigger it.

**Recommended operational pattern:**

```
1. Stop application traffic
2. Dump the database (per backup-and-restore.md)
3. Run migrations
4. Verify (health_check + spot-check node counts)
5. Resume application traffic
```

---

## 7. Restore-mid-migration: failure and recovery strategy

### What happens if a migration fails partway?

**Proposed approach: Fail-fast + restore from dump.**

The runner stops immediately on any exception. It does **not** attempt
to roll back via `down()`, resume from a partial state, or continue to
the next migration.

### Why not automated rollback via `down()`?

| Approach | Pros | Cons |
|----------|------|------|
| **Automated `down()` on failure** | Clean, self-contained recovery | Graph mutations are rarely cleanly reversible — `SET user_id = ""` can't be undone without knowing the "before" state (which was `NULL`, but how do you distinguish "was NULL before migration" from "was NULL because it was just created"?). Partial `down()` execution is itself a failure mode. |
| **Resume from partial state** | No data loss, no dump needed | Requires tracking per-node progress within a migration, dramatically increases complexity. Violates the "under 20 lines" design goal. |
| **Fail-fast + dump restore** (recommended) | Simple, reliable, leverages existing tooling | Requires operator to have taken a dump first (which they should always do). Longer recovery time for very large graphs. |

**Recommendation: Fail-fast + dump restore.** This is the right choice
for `ragleap-graph`'s current scale and maturity:

1. The library is pre-1.0 (`Development Status :: 3 - Alpha`).
2. Existing deployments are small enough that dump/restore takes seconds
   to low minutes.
3. Both existing migrations are idempotent — a restored-then-re-run
   cycle is safe and tested.
4. Building a resume-capable or rollback-capable runner would be
   significant engineering for a problem that hasn't occurred yet.

### Recovery procedure

When `run_pending()` raises `RuntimeError`:

1. **Read the error message.** It identifies which migration failed and
   includes the original exception.
2. **Assess the damage.** The graph may be in a partial state (e.g.,
   half the nodes have been backfilled). This is not corruption — it's
   an incomplete migration.
3. **Decide: retry or restore.**
   - If the failure was transient (e.g., Neo4j ran out of memory on a
     large batch), you can re-run the migration. Idempotent migrations
     will skip already-processed nodes.
   - If the failure was a bug in the migration itself, restore from the
     pre-migration dump (see `backup-and-restore.md`), fix the
     migration, and re-run.
4. **After a successful restore**, the `:_Migration` tracking nodes are
   also restored to their pre-migration state (since they're in the same
   dump), so `run_pending()` will correctly re-apply the failed migration.

---

## 8. Future considerations (not proposed for v1)

- **CLI entry point**: `python -m ragleap_graph.migrate` for operators
  who prefer command-line invocation over Python scripts.
- **Namespace-scoped migrations**: Some migrations (like both current
  ones) accept `namespace=` to scope the backfill. The `Migration`
  interface could support this via an optional constructor parameter.
- **Uniqueness constraint on `:_Migration.id`**: Prevents duplicate
  tracking nodes from concurrent runner executions (see Section 6).
- **Pre-migration health checks**: A `check()` method on `Migration`
  that validates preconditions (e.g., "expected node label exists")
  before running `up()`.
- **Integration with `AuditLogger`**: Log migration events to the audit
  table alongside normal operation audits.

---

## 9. Open questions for maintainers

1. **Should `run_pending()` log a backup warning?** A `WARNING`-level
   log at the start of `run_pending()` saying "ensure you have a
   database dump before proceeding" is cheap insurance. Alternatively,
   the runner could accept a `--i-have-a-backup` flag and refuse to run
   without it. Both are lightweight; the question is whether the nudge
   is helpful or annoying.

2. **Where should migration classes live?** Options:
   - `ragleap_graph/migrations/` (a new subpackage)
   - `ragleap_graph/_migrations.py` (single file, `_`-prefixed as internal)
   - Alongside `__init__.py` as `ragleap_graph/schema_migrations.py`

3. **Should the existing `backfill_*()` methods be deprecated once the
   framework ships?** They could remain as convenience wrappers that
   internally delegate to the migration framework, or they could be left
   as-is with a deprecation notice pointing to the runner.

4. **Concurrency guard**: Should the runner attempt to acquire a Neo4j
   lock (e.g., `MERGE (lock:_MigrationLock {active: true})`) to prevent
   concurrent runner executions, or is the "run during maintenance
   window" guidance sufficient?

---

*This is a design proposal, not an implementation commitment. See
[ADR-0001](../adr/0001-backup-restore-ownership.md) for the related
decision on backup/restore ownership.*
