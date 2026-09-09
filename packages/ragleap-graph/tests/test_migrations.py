"""
Tests for ragleap_graph.migrations - the schema migration framework.
See docs/design/schema-migrations.md for the full design rationale.
"""
import os
import uuid
import pytest

from ragleap_graph.migrations import Migration, MigrationRunner, ALL_MIGRATIONS

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
HAS_LIVE_NEO4J = bool(NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD)
TEST_NAMESPACE = "pytest-migrations-ns"


# ---------------------------------------------------------------------------
# Fakes for offline MigrationRunner logic tests - no live Neo4j required.
# ---------------------------------------------------------------------------

class FakeResult:
    def __init__(self, record):
        self._record = record

    def single(self):
        return self._record


class FakeSession:
    """Minimal fake mimicking neo4j.Session, just enough for
    MigrationRunner/Migration.is_applied() to operate against."""

    def __init__(self, applied_ids=None):
        self.applied_ids = set(applied_ids or [])
        self.created_migration_records = []
        self.run_calls = []

    def run(self, query, **params):
        self.run_calls.append((query, params))
        if "RETURN count(m) > 0 AS applied" in query:
            applied = params.get("id") in self.applied_ids
            return FakeResult({"applied": applied})
        if "CREATE (m:_Migration" in query:
            self.created_migration_records.append(dict(params))
            self.applied_ids.add(params["id"])
            return FakeResult(None)
        if "RETURN m.applied_at AS applied_at" in query:
            return FakeResult({"applied_at": "2026-01-01T00:00:00Z", "elapsed_ms": 42})
        raise AssertionError(f"Unexpected query in FakeSession.run: {query!r}")


class FakeSessionContextManager:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *a):
        return False


class FakeDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return FakeSessionContextManager(self._session)


class FakeMigration(Migration):
    """A test-double Migration for exercising MigrationRunner logic
    without depending on the two real, concrete migrations."""

    def __init__(self, id_, description="fake migration", up_fn=None, up_result=None):
        self._id = id_
        self._description = description
        self._up_fn = up_fn
        self._up_result = up_result if up_result is not None else {"updated": 1}

    @property
    def id(self):
        return self._id

    @property
    def description(self):
        return self._description

    def up(self, session):
        if self._up_fn is not None:
            return self._up_fn(session)
        return self._up_result


# ---------------------------------------------------------------------------
# Offline tests - MigrationRunner logic
# ---------------------------------------------------------------------------

def test_migration_runner_requires_driver():
    with pytest.raises(RuntimeError, match="requires an active Neo4j driver"):
        MigrationRunner(None, [])


def test_migration_runner_sorts_migrations_by_id():
    m_b = FakeMigration("0002_second")
    m_a = FakeMigration("0001_first")
    fake_session = FakeSession()
    fake_driver = FakeDriver(fake_session)
    runner = MigrationRunner(fake_driver, [m_b, m_a])
    assert [m.id for m in runner.migrations] == ["0001_first", "0002_second"]


def test_run_pending_dry_run_reports_without_executing():
    called = []

    def up_fn(session):
        called.append(True)
        return {"updated": 99}

    migration = FakeMigration("0001_test", up_fn=up_fn)
    fake_session = FakeSession()
    fake_driver = FakeDriver(fake_session)
    runner = MigrationRunner(fake_driver, [migration])

    results = runner.run_pending(dry_run=True)

    assert not called, "dry_run must not actually invoke up()"
    assert len(results) == 1
    assert results[0]["status"] == "pending"
    assert results[0]["id"] == "0001_test"
    assert not fake_session.created_migration_records, (
        "dry_run must not create any :_Migration tracking nodes"
    )


def test_run_pending_skips_already_applied_migrations():
    migration = FakeMigration("0001_already_done")
    fake_session = FakeSession(applied_ids={"0001_already_done"})
    fake_driver = FakeDriver(fake_session)
    runner = MigrationRunner(fake_driver, [migration])

    results = runner.run_pending()

    assert results == [], "an already-applied migration should not appear in results"
    assert not fake_session.created_migration_records


def test_run_pending_applies_pending_migrations_and_records_them():
    migration = FakeMigration(
        "0001_test", description="does a thing", up_result={"Entity": 5}
    )
    fake_session = FakeSession()
    fake_driver = FakeDriver(fake_session)
    runner = MigrationRunner(fake_driver, [migration])

    results = runner.run_pending()

    assert len(results) == 1
    assert results[0]["status"] == "applied"
    assert results[0]["id"] == "0001_test"
    assert results[0]["result"] == {"Entity": 5}
    assert "elapsed_ms" in results[0]

    assert len(fake_session.created_migration_records) == 1
    record = fake_session.created_migration_records[0]
    assert record["id"] == "0001_test"
    assert record["description"] == "does a thing"


def test_run_pending_stops_on_first_failure_and_does_not_continue():
    def failing_up(session):
        raise ValueError("simulated migration failure")

    m1 = FakeMigration("0001_fails", up_fn=failing_up)
    called_second = []
    m2 = FakeMigration(
        "0002_never_reached",
        up_fn=lambda session: called_second.append(True) or {},
    )
    fake_session = FakeSession()
    fake_driver = FakeDriver(fake_session)
    runner = MigrationRunner(fake_driver, [m1, m2])

    with pytest.raises(RuntimeError, match="0001_fails"):
        runner.run_pending()

    assert not called_second, "runner must not proceed to the next migration after a failure"
    assert not fake_session.created_migration_records, (
        "a failed migration's :_Migration record must not be created"
    )


def test_status_reports_applied_and_pending():
    applied_migration = FakeMigration("0001_applied")
    pending_migration = FakeMigration("0002_pending")
    fake_session = FakeSession(applied_ids={"0001_applied"})
    fake_driver = FakeDriver(fake_session)
    runner = MigrationRunner(fake_driver, [applied_migration, pending_migration])

    statuses = runner.status()

    by_id = {s["id"]: s for s in statuses}
    assert by_id["0001_applied"]["applied"] is True
    assert "applied_at" in by_id["0001_applied"]
    assert by_id["0002_pending"]["applied"] is False
    assert "applied_at" not in by_id["0002_pending"]


def test_migration_down_default_raises_not_implemented():
    migration = FakeMigration("0001_test")
    with pytest.raises(NotImplementedError, match="does not support down"):
        migration.down(session=None)


def test_all_migrations_registry_has_unique_sortable_ids():
    ids = [m.id for m in ALL_MIGRATIONS]
    assert len(ids) == len(set(ids)), "ALL_MIGRATIONS must not have duplicate ids"
    assert ids == sorted(ids), "ALL_MIGRATIONS should already be in sorted order"


# ---------------------------------------------------------------------------
# Live test - real Neo4j, exercises the real registered migrations end-to-end
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_LIVE_NEO4J, reason="No live Neo4j credentials in environment")
def test_migration_runner_live_dry_run_then_apply_is_idempotent():
    """
    Real end-to-end test against live Neo4j: dry_run reports the real
    registered migrations as pending (assuming a clean namespace with
    no prior :_Migration nodes), applying them creates real :_Migration
    tracking nodes, and running again afterward is a correct no-op -
    matching the idempotency guarantee both underlying backfill methods
    already document and the design doc's own stated behavior.
    """
    from ragleap_graph import GraphConfig, GraphIndex

    config = GraphConfig(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    graph = GraphIndex(config=config)

    # Use a throwaway id-suffix per real migration so this test's own
    # :_Migration nodes never collide with any other test run's, since
    # :_Migration nodes are graph-global, not namespace-scoped.
    suffix = uuid.uuid4().hex[:8]

    class TestMigration(Migration):
        def __init__(self, base_id):
            self._id = f"{base_id}_test_{suffix}"

        @property
        def id(self):
            return self._id

        @property
        def description(self):
            return f"live-test copy of {self._id}"

        def up(self, session):
            # Real, harmless no-op write against the live database -
            # proves the runner's session plumbing and :_Migration
            # bookkeeping work against a real driver, without touching
            # any real application data.
            session.run(
                "MERGE (t:_MigrationLiveTestMarker {suffix: $suffix}) "
                "SET t.touched_at = datetime()",
                suffix=suffix,
            )
            return {"marked": True}

    test_migrations = [TestMigration("0001"), TestMigration("0002")]

    try:
        runner = MigrationRunner(graph.driver, test_migrations)

        pending = runner.run_pending(dry_run=True)
        assert len(pending) == 2, (
            f"expected both fresh test migrations to be pending, got {pending}"
        )
        assert all(p["status"] == "pending" for p in pending)

        applied = runner.run_pending()
        assert len(applied) == 2
        assert all(a["status"] == "applied" for a in applied)
        assert all(a["result"] == {"marked": True} for a in applied)

        # Idempotency: running again finds both already applied.
        second_run = runner.run_pending()
        assert second_run == [], (
            "expected zero migrations to run on the second call - "
            "both should already be recorded as applied"
        )

        statuses = runner.status()
        assert all(s["applied"] for s in statuses)
        assert all("applied_at" in s for s in statuses)
    finally:
        with graph.driver.session() as session:
            session.run(
                "MATCH (m:_Migration) WHERE m.id ENDS WITH $suffix DETACH DELETE m",
                suffix=suffix,
            )
            session.run(
                "MATCH (t:_MigrationLiveTestMarker {suffix: $suffix}) DETACH DELETE t",
                suffix=suffix,
            )
        graph.close()
