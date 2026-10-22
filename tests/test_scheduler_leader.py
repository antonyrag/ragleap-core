"""Scheduler leader lock: only one process runs the background jobs. Unit tests use fake connections;
one test uses the real database when DATABASE_URL is set."""
import asyncio
import os
import time

import pytest

from core import scheduler_leader as sl


class FakeCur:
    def __init__(self, conn):
        self.conn = conn
        self.last = None

    def execute(self, sql, params=None):
        if self.conn.dead:
            raise RuntimeError("connection lost")
        self.last = sql
        self.conn.queries.append(sql)

    def fetchone(self):
        if "pg_try_advisory_lock" in self.last:
            return (self.conn.grant,)
        return (1,)

    def close(self):
        pass


class FakeConn:
    def __init__(self, grant=True):
        self.grant = grant
        self.dead = False
        self.closed = False
        self.queries = []

    def cursor(self):
        return FakeCur(self)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _clean():
    sl.release()
    yield
    sl.release()


def test_enabled_by_default_and_switch_off(monkeypatch):
    assert sl.enabled() is True
    for v in ("false", "0", "no", "OFF"):
        monkeypatch.setenv("SCHEDULER_ENABLED", v)
        assert sl.enabled() is False


def test_disabled_never_connects(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setattr(sl, "_connect", lambda: (_ for _ in ()).throw(AssertionError("must not connect")))
    assert sl.is_leader() is False


def test_the_winner_keeps_one_connection(monkeypatch):
    conns = []

    def connect():
        c = FakeConn(grant=True)
        conns.append(c)
        return c
    monkeypatch.setattr(sl, "_connect", connect)
    assert sl.is_leader() is True
    assert sl.is_leader() is True
    assert len(conns) == 1 and not conns[0].closed
    assert any("pg_try_advisory_lock" in q for q in conns[0].queries)


def test_a_loser_closes_its_connection_and_retries_next_time(monkeypatch):
    conns = []

    def connect():
        c = FakeConn(grant=False)
        conns.append(c)
        return c
    monkeypatch.setattr(sl, "_connect", connect)
    assert sl.is_leader() is False
    assert sl.is_leader() is False
    assert len(conns) == 2 and all(c.closed for c in conns)


def test_takeover_after_the_leader_connection_dies(monkeypatch):
    conns = []

    def connect():
        c = FakeConn(grant=True)
        conns.append(c)
        return c
    monkeypatch.setattr(sl, "_connect", connect)
    assert sl.is_leader() is True
    conns[0].dead = True
    assert sl.is_leader() is True
    assert len(conns) == 2 and conns[0].closed and not conns[1].closed


def test_connection_failure_means_not_leader_and_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("database down")
    monkeypatch.setattr(sl, "_connect", boom)
    assert sl.is_leader() is False


def test_release_closes_the_connection(monkeypatch):
    c = FakeConn(grant=True)
    monkeypatch.setattr(sl, "_connect", lambda: c)
    assert sl.is_leader() is True
    sl.release()
    assert c.closed is True
    sl.release()


def test_leader_only_runs_the_job_in_the_leader_only(monkeypatch):
    ran = []

    async def job():
        ran.append(1)
    wrapped = sl.leader_only(job)
    monkeypatch.setattr(sl, "is_leader", lambda: False)
    asyncio.run(wrapped())
    assert ran == []
    monkeypatch.setattr(sl, "is_leader", lambda: True)
    asyncio.run(wrapped())
    assert ran == [1]


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs the test database")
def test_with_the_real_database_a_second_connection_cannot_lead():
    import psycopg2
    assert sl.is_leader() is True
    other = psycopg2.connect(os.environ["DATABASE_URL"])
    other.autocommit = True
    try:
        cur = other.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s)", (sl.LOCK_KEY,))
        assert cur.fetchone()[0] is False
        sl.release()
        # Closing a connection does not free its lock at once: the server ends the session a moment later.
        got = False
        for _ in range(50):
            cur.execute("SELECT pg_try_advisory_lock(%s)", (sl.LOCK_KEY,))
            got = cur.fetchone()[0]
            if got:
                break
            time.sleep(0.1)
        assert got is True
        cur.execute("SELECT pg_advisory_unlock(%s)", (sl.LOCK_KEY,))
    finally:
        other.close()
