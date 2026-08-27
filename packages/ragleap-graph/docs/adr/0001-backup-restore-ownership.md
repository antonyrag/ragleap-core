# ADR-0001: Backup/Restore Ownership for ragleap-graph

| Field        | Value                                                    |
|--------------|----------------------------------------------------------|
| **Status**   | Proposed (pending maintainer sign-off)                   |
| **Date**     | 2026-08-27                                               |
| **Context**  | Issue: missing backup/restore tooling for Neo4j graph    |
| **Relates**  | `docs/operations/backup-and-restore.md`, `docs/design/schema-migrations.md` |

---

## Context and problem statement

`ragleap-graph` stores knowledge-graph data in Neo4j but provides no
backup or restore functionality. As the library adds schema migrations
(e.g., `backfill_user_id_defaults()` in v0.6.5, `backfill_composite_key()`
in v0.6.7), operators need a reliable way to snapshot the graph before
running potentially destructive changes. The core question is:

**Should backup/restore be `ragleap-graph`'s own responsibility (built
into the library), or should it be explicitly out of scope (delegated to
Neo4j's native tooling and the operator's infrastructure)?**

---

## Decision drivers

1. **Maintenance burden**: `neo4j-admin database dump/load` is a
   mature, well-tested tool maintained by Neo4j Inc. Building a Python
   wrapper around it means maintaining compatibility across Neo4j 4.x
   and 5.x, Community and Enterprise editions, Docker and bare-metal
   deployments, and across `neo4j-admin` CLI changes between versions.

2. **Security and permission boundaries**: `neo4j-admin` operates on
   the database files directly — it needs filesystem access to the Neo4j
   data directory and typically requires the database to be stopped
   (Community Edition). A Python library connecting via Bolt protocol
   cannot orchestrate this without shell access to the Neo4j host, which
   is a fundamentally different privilege level than "connect and query."

3. **Footgun risk**: A library-managed backup that works for Docker
   Compose but fails silently for Kubernetes, bare-metal, or managed
   Neo4j (Aura) deployments is worse than no backup — it gives a false
   sense of safety. The operator who believes their backups are handled
   is more vulnerable than the one who knows they aren't.

4. **Scope alignment**: `ragleap-graph` is a knowledge-graph *retrieval*
   library (`pyproject.toml`: `Development Status :: 3 - Alpha`). Its
   core value proposition is entity extraction, graph construction, and
   graph-augmented retrieval — not database administration. Adding DBA
   tooling expands the maintenance surface without improving the core
   use case.

5. **Precedent within the ecosystem**: `ragleap-rag` (the sibling
   package) stores data in Postgres but does not wrap `pg_dump` /
   `pg_restore`. It provides `init_schema()` for table creation but
   delegates all backup/restore to the operator's Postgres
   infrastructure. Consistency across the ecosystem argues for the same
   pattern.

---

## Options considered

### Option 1: Built-in Python backup orchestration

Wrap `neo4j-admin dump/load` (or use APOC export procedures) in a
Python API on `GraphIndex`, e.g.:

```python
graph.backup(path="/backups/pre-migration.dump")
graph.restore(path="/backups/pre-migration.dump")
```

**Pros:**
- Single-command backup from the same Python process running migrations.
- Lower barrier for operators unfamiliar with `neo4j-admin`.

**Cons:**
- Requires shell access to the Neo4j host (subprocess calls or SSH),
  fundamentally different from Bolt-protocol access.
- `neo4j-admin` CLI syntax differs between Neo4j 4.x and 5.x, Community
  and Enterprise, making the wrapper fragile.
- Docker deployments require `docker exec` into the container — the
  Python library has no way to know the container name/ID.
- Managed Neo4j (Aura) does not expose `neo4j-admin` at all.
- APOC-based exports (`apoc.export.*`) are not available by default
  (`NEO4J_PLUGINS: '[]'` in the project's `docker-compose.yml`) and
  produce Cypher/JSON/CSV, not a full database-consistent dump.
- Significant ongoing maintenance burden for a non-core feature.
- False sense of safety if the wrapper works in dev but fails in prod.

### Option 2: Documentation + native tooling (recommended)

Provide a clear operational guide (`docs/operations/backup-and-restore.md`)
documenting the recommended manual procedure using `neo4j-admin`, and
explicitly declare that `ragleap-graph` does not own this lifecycle.

**Pros:**
- Zero maintenance burden — Neo4j maintains the tooling.
- Works across all deployment models (Docker, bare-metal, Kubernetes,
  managed).
- Honest about the library's scope — operators know they own this.
- Pre-migration checklist in the docs creates a clear operational ritual.
- Consistent with `ragleap-rag`'s approach to Postgres backup.

**Cons:**
- Higher barrier for operators unfamiliar with `neo4j-admin`.
- Risk of operators skipping the backup step before migrations (but this
  risk exists regardless — a built-in backup that the operator forgets
  to call is equally useless).

---

## Recommendation

**Option 2: Documentation + native tooling.**

The library should:

1. **Ship `docs/operations/backup-and-restore.md`** (done) with a
   concrete, tested procedure for offline dump and restore.
2. **Reference the backup doc prominently** in migration error messages
   and the proposed `MigrationRunner`'s output.
3. **Not wrap or invoke `neo4j-admin`** from Python code.
4. **Explicitly state** in the README and migration docs that backup is
   the operator's responsibility, not the library's.

This recommendation is framed for maintainer sign-off — it should be
adopted, amended, or rejected by the project maintainer, not treated as
a unilateral decision.

---

## Consequences

### If accepted

- `ragleap-graph` gains operational documentation but no new Python code
  for backup/restore.
- The `MigrationRunner` (per `schema-migrations.md`) will include
  guidance to dump before migrating, but will not enforce or automate it.
- Future issues requesting "add a backup button" can be closed with a
  reference to this ADR and the operational docs.

### If rejected (in favor of Option 1)

- A new `ragleap_graph.backup` module would need to be scoped, covering:
  which deployment models to support, how to discover the Neo4j
  container/process, how to handle `neo4j-admin` version differences,
  and what the testing strategy is across all of these.
- The issue explicitly lists "do NOT implement a full backup product or
  wrap `neo4j-admin`" as a non-goal, so rejecting this ADR in favor of
  Option 1 would need a scope change justification.

---

*This ADR follows the format from
[Michael Nygard's article](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).*
