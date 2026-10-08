import os

import psycopg2
import pytest

from core import vector_dims as vd

T, IDX = "zz_vec_x", "zz_vec_x_idx"


@pytest.fixture
def conn():
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = c.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {T}")
    cur.execute(f"CREATE TABLE {T} (id serial PRIMARY KEY, embedding vector(3072))")
    cur.execute(f"CREATE INDEX {IDX} ON {T} USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)")
    c.commit()
    yield c
    c.rollback()
    cur = c.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {T}")
    c.commit()
    c.close()


def _index_def(conn):
    cur = conn.cursor()
    cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = %s", (IDX,))
    row = cur.fetchone()
    return row[0] if row else None


def _col(conn):
    return vd.column_dims(conn.cursor(), T, "embedding")


def test_equal_is_noop(conn):
    assert vd.ensure_table(conn, T, "embedding", IDX, 3072)["status"] == "ok"
    assert _col(conn) == 3072 and "halfvec(3072)" in _index_def(conn)


def test_empty_table_is_resized(conn):
    r = vd.ensure_table(conn, T, "embedding", IDX, 768)
    assert r["status"] == "adjusted" and _col(conn) == 768
    assert "halfvec(768)" in _index_def(conn)


def test_rows_block_change(conn):
    cur = conn.cursor()
    cur.execute(f"INSERT INTO {T} (embedding) VALUES (%s::vector)", ("[" + ",".join(["0.1"] * 3072) + "]",))
    conn.commit()
    r = vd.ensure_table(conn, T, "embedding", IDX, 768)
    assert r["status"] == "mismatch" and r["rows"] == 1
    assert _col(conn) == 3072 and "halfvec(3072)" in _index_def(conn)


def test_big_dims_no_index(conn):
    r = vd.ensure_table(conn, T, "embedding", IDX, 4096)
    assert r["status"] == "adjusted" and _col(conn) == 4096
    assert _index_def(conn) is None


def test_invalid_and_missing(conn):
    assert vd.ensure_table(conn, T, "embedding", IDX, 0)["status"] == "invalid"
    assert vd.ensure_table(conn, "zz_no_such_table", "embedding", "zz_i", 768)["status"] == "missing"


def test_status_is_read_only_and_reports_each_case(conn, monkeypatch):
    monkeypatch.setattr(vd, "TARGETS", [(T, "embedding", IDX)])
    assert vd.status(3072) == [{"table": T, "status": "ok", "have": 3072, "want": 3072, "rows": 0}]
    r = vd.status(768)[0]
    assert r["status"] == "will_resize" and r["have"] == 3072 and _col(conn) == 3072
    cur = conn.cursor()
    cur.execute(f"INSERT INTO {T} (embedding) VALUES (%s::vector)", ("[" + ",".join(["0.1"] * 3072) + "]",))
    conn.commit()
    r = vd.status(768)[0]
    assert r["status"] == "mismatch" and r["rows"] == 1 and _col(conn) == 3072


def test_status_missing_table(monkeypatch):
    monkeypatch.setattr(vd, "TARGETS", [("zz_no_such_table", "embedding", "zz_i")])
    assert vd.status(768)[0]["status"] == "missing"
