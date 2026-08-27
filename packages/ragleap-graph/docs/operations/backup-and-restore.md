# Backup and Restore — ragleap-graph (Stopgap Procedure)

> **Status: Stopgap.**
> `ragleap-graph` does **not** currently orchestrate or automate Neo4j backups itself.
> This document describes a recommended manual procedure using Neo4j's own
> `neo4j-admin` tooling. It exists so operators have a clear, tested path
> before running schema migrations or making destructive graph changes —
> not because `ragleap-graph` manages this lifecycle for you.

---

## 1. Background

`ragleap-graph` stores all knowledge-graph data (`:Entity`, `:Document`,
`:PairWeight`, `:RelationWeight` nodes and their relationships) in a
Neo4j database. The library itself has no backup/restore API — it
delegates all data-at-rest management to Neo4j's native tooling.

As of v0.6.7, the graph also contains per-label `composite_key` uniqueness
constraints (created idempotently on every `GraphIndex` connect) and
internal `:_Migration` tracking nodes (proposed — see
[schema-migrations.md](../design/schema-migrations.md)). Both are part of
the database state and are included in a full dump.

---

## 2. Where ragleap-graph expects Neo4j data to live

### Docker Compose (default setup)

From the project's `docker-compose.yml`:

```yaml
neo4j:
  image: neo4j:5-community
  volumes:
    - ragleap_core_neo4j_data:/data
```

The named volume `ragleap_core_neo4j_data` maps to Neo4j's `/data`
directory inside the container. Within that:

| Path (inside container)          | Contents                              |
|----------------------------------|---------------------------------------|
| `/data/databases/neo4j/`         | The default database's store files    |
| `/data/transactions/neo4j/`      | Transaction logs                      |

### Bare-metal / self-managed Neo4j

If you're running Neo4j outside Docker, the data directory is controlled
by `server.directories.data` in `neo4j.conf` (typically
`/var/lib/neo4j/data` on Linux, `C:\neo4j\data` on Windows). The
database name is `neo4j` unless you've explicitly created a different one.

### Environment variables

`ragleap-graph` connects via `GraphConfig(uri=, user=, password=)`,
typically sourced from environment variables:

| Variable          | Default                   | Purpose                    |
|-------------------|---------------------------|----------------------------|
| `NEO4J_URI`       | `bolt://localhost:7687`   | Bolt protocol endpoint     |
| `NEO4J_USER`      | `neo4j`                   | Authentication username    |
| `NEO4J_PASSWORD`  | *(empty)*                 | Authentication password    |

These are connection-level settings only — the backup procedure operates
on the database files, not through the Bolt protocol.

---

## 3. Online vs. offline dump tradeoffs

| Approach | Command | Requires DB shutdown? | Neo4j Edition | Consistency guarantee |
|---|---|---|---|---|
| **Offline dump** | `neo4j-admin database dump` | **Yes** — database must be stopped | Community + Enterprise | Full — no concurrent writes during dump |
| **Online dump** | `neo4j-admin database dump --to-stdout` (4.x) or backup commands (5.x Enterprise) | No | Enterprise only (online backup) | Transaction-consistent snapshot |
| **Volume snapshot** | Docker volume / filesystem snapshot | Recommended to stop first | Any | Depends on filesystem (crash-consistent at best) |

**For most `ragleap-graph` deployments** (Community Edition, Docker Compose),
the offline dump is the recommended approach. The downtime window is
typically seconds to low minutes for graphs under a few hundred thousand
nodes.

---

## 4. Pre-migration checklist — dump before you migrate

Run this checklist **before** executing any migration (e.g.,
`backfill_user_id_defaults()`, `backfill_composite_key()`, or any future
migration registered with the proposed migration framework).

### Checklist

- [ ] **Confirm the Neo4j version**: `neo4j-admin --version`. Dump/load
      command syntax differs between Neo4j 4.x and 5.x.
- [ ] **Stop application writes**: Shut down all `ragleap-graph`
      application instances (or pause traffic) so no `upsert_document()`
      calls are in flight during the dump.
- [ ] **Stop the Neo4j database** (Community Edition):
  ```bash
  # Docker Compose
  docker compose stop neo4j

  # Bare-metal
  neo4j stop
  ```
- [ ] **Run the dump**:
  ```bash
  # Neo4j 5.x (Community) — from the host, into the container
  docker compose exec neo4j neo4j-admin database dump neo4j \
      --to-path=/data/backups/

  # Or, bare-metal
  neo4j-admin database dump neo4j --to-path=/var/lib/neo4j/backups/
  ```
  The dump file will be named `neo4j.dump` (matching the database name).
- [ ] **Copy the dump to a safe location** outside the Neo4j data volume:
  ```bash
  # Docker — copy out of the container
  docker compose cp neo4j:/data/backups/neo4j.dump ./backups/neo4j-$(date +%Y%m%d-%H%M%S).dump

  # Bare-metal
  cp /var/lib/neo4j/backups/neo4j.dump ~/backups/neo4j-$(date +%Y%m%d-%H%M%S).dump
  ```
- [ ] **Verify the dump file** is non-empty and has a reasonable size
      relative to your known data volume.
- [ ] **Restart Neo4j**:
  ```bash
  docker compose start neo4j
  # or: neo4j start
  ```
- [ ] **Verify connectivity** before running the migration:
  ```python
  from ragleap_graph import GraphIndex, GraphConfig
  g = GraphIndex(config=GraphConfig(uri="bolt://localhost:7688",
                                     user="neo4j", password="ragleapgraph"))
  assert g.health_check(), "Neo4j is not responding after restart"
  ```
- [ ] **Now run the migration.** If it fails partway, see the restore
      procedure below.

---

## 5. Restore walkthrough

Use this procedure if a migration or other operation has left the graph
in a bad state and you need to roll back to the pre-migration dump.

### Step 1: Stop everything

```bash
# Stop the application
docker compose stop app

# Stop Neo4j
docker compose stop neo4j
```

### Step 2: Drop the current (corrupted/partial) database

For Neo4j 5.x Community, the simplest approach is to remove the database
directory and let `load` recreate it:

```bash
# Docker — remove the database files inside the volume
docker compose run --rm neo4j bash -c \
    "rm -rf /data/databases/neo4j /data/transactions/neo4j"
```

> [!CAUTION]
> This **permanently destroys** the current database contents. Only do
> this if you have a verified dump file from the pre-migration checklist.

### Step 3: Load the dump

```bash
# Neo4j 5.x
docker compose run --rm neo4j neo4j-admin database load neo4j \
    --from-path=/data/backups/ --overwrite-destination

# Bare-metal
neo4j-admin database load neo4j \
    --from-path=/var/lib/neo4j/backups/ --overwrite-destination
```

### Step 4: Restart and verify

```bash
docker compose start neo4j
# Wait for healthcheck to pass (configured as 10s interval, 10 retries)

docker compose start app
```

Verify the graph is back to pre-migration state:

```python
from ragleap_graph import GraphIndex, GraphConfig

g = GraphIndex(config=GraphConfig(uri="bolt://localhost:7688",
                                   user="neo4j", password="ragleapgraph"))
assert g.health_check()

# Spot-check: confirm node counts match expectations
with g.driver.session() as s:
    for label in ["Document", "Entity", "PairWeight", "RelationWeight"]:
        count = s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
        print(f"{label}: {count} nodes")
```

### Step 5: Investigate the migration failure

Before re-running the failed migration:
1. Check the migration's error output / logs.
2. If the migration itself has a bug, fix the migration code first.
3. Re-run the pre-migration checklist (dump again before retrying).

---

## 6. What this document does NOT cover

- **Automated/scheduled backups**: Out of scope for `ragleap-graph`.
  Use your infrastructure's native scheduling (cron, Kubernetes CronJob,
  cloud-provider snapshot policies).
- **Point-in-time recovery**: Requires Neo4j Enterprise Edition's
  transaction log archiving. Not available on Community Edition.
- **Cross-version Neo4j upgrades**: `neo4j-admin database dump/load` is
  version-specific. For major Neo4j version upgrades, consult Neo4j's
  own [migration guide](https://neo4j.com/docs/operations-manual/current/upgrade/).
- **Postgres backup**: The audit log (if enabled via `AuditConfig`) is
  stored in Postgres, not Neo4j. Back up Postgres separately using
  `pg_dump` / `pg_restore`.

---

*Last updated: v0.6.7. This procedure should be reviewed whenever the
Neo4j data model changes (new node labels, new constraints) or when
`ragleap-graph` adds its own migration framework.*
