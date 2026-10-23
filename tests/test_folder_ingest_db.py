"""Folder auto-ingest against the real database (db/schema.sql applied): the source columns on documents, the first-sync
approval table, the documents list, and the two API routes. The embedding, graph and language calls are replaced."""
import asyncio
import uuid

import pytest

from core import document_store, folder_ingest as fi

KEY = {"x-api-key": "k-test"}


def _client(monkeypatch):
    from fastapi.testclient import TestClient
    from core import api
    monkeypatch.setattr(api, "RAGLEAP_API_KEY", "k-test")
    return TestClient(api.app)


def _grant():
    return "pytest-" + uuid.uuid4().hex[:8]


def _sql(sql, args=(), fetch=False):
    conn = document_store._connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, args)
        rows = cur.fetchall() if fetch else None
        conn.commit()
        return rows
    finally:
        conn.close()


@pytest.fixture
def fake_ingest_deps(monkeypatch):
    """ingest_document with a fake embedder of the column's real size, no graph and a fixed language."""
    from core import ingest, vector_dims
    conn = document_store._connect()
    try:
        dims = vector_dims.column_dims(conn.cursor(), "chunks", "embedding") or 3072
    finally:
        conn.close()

    class FakeEmbedder:
        def embed_text(self, text):
            return [0.001] * dims

    monkeypatch.setattr(ingest, "EmbeddingService", FakeEmbedder)
    monkeypatch.setattr(ingest.graph_service, "upsert_document_graph", lambda *a, **k: None)
    monkeypatch.setattr(ingest.language_detector, "detect_language", lambda text: ("en", 0.9))
    return ingest


def test_the_schema_is_applied_in_this_database():
    assert fi._schema_ready() is True


def test_approvals_are_recorded_and_can_be_repeated():
    grant = _grant()
    try:
        assert fi._approved(grant) is False
        fi._approve(grant, 3)
        fi._approve(grant, 5)
        assert fi._approved(grant) is True
        assert _sql("SELECT approved_files FROM folder_ingest_approvals WHERE grant_name = %s", (grant,), True) == [(5,)]
    finally:
        _sql("DELETE FROM folder_ingest_approvals WHERE grant_name = %s", (grant,))


def test_a_document_from_a_folder_keeps_its_source_and_a_plain_one_has_none(fake_ingest_deps):
    ingest = fake_ingest_deps
    grant = _grant()
    plain = folder = None
    try:
        folder = ingest.ingest_document(grant + "/sub/a.txt", "hello folder world " * 20,
                                        source={"grant": grant, "path": "sub/a.txt", "hash": "a" * 64})["document_id"]
        plain = ingest.ingest_document("pytest-plain-" + grant + ".txt", "hello plain world " * 20)["document_id"]
        assert fi._ingested(grant) == {"sub/a.txt": [(folder, "a" * 64)]}
        docs = {d["id"]: d for d in document_store.list_documents(limit=500)}
        assert docs[folder]["source"] == {"grant": grant, "path": "sub/a.txt"} and docs[folder]["chunks"] >= 1
        assert docs[plain]["source"] is None
    finally:
        for doc_id in (folder, plain):
            if doc_id:
                document_store.delete_document(doc_id)
    assert fi._ingested(grant) == {}


def test_the_documents_list_still_works_before_the_schema_is_applied(monkeypatch):
    class UndefinedColumn(Exception):
        pass

    class Cur:
        def __init__(self):
            self.runs = 0

        def execute(self, sql, args=()):
            self.runs += 1
            if "source_grant" in sql:
                raise UndefinedColumn("column d.source_grant does not exist")

        def fetchall(self):
            return [("11111111-1111-1111-1111-111111111111", "old.txt", None, 2)]

    cur = Cur()

    class Conn:
        rolled = False

        def cursor(self):
            return cur

        def rollback(self):
            Conn.rolled = True

        def close(self):
            pass

    monkeypatch.setattr(document_store, "_connect", lambda: Conn())
    assert document_store.list_documents() == [{"id": "11111111-1111-1111-1111-111111111111", "filename": "old.txt",
                                                "uploaded_at": None, "chunks": 2, "source": None}]
    assert Conn.rolled and cur.runs == 2


def test_other_database_errors_in_the_list_are_not_hidden(monkeypatch):
    class Cur:
        def execute(self, sql, args=()):
            raise RuntimeError("connection lost")

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            pass

    monkeypatch.setattr(document_store, "_connect", lambda: Conn())
    with pytest.raises(RuntimeError):
        document_store.list_documents()


# ---------------- the API routes ----------------

def test_the_routes_need_the_key(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/folder-ingest").status_code == 401
    assert c.post("/folder-ingest/approve", json={"grant": "docs"}).status_code == 401
    assert c.post("/folder-ingest/approve", json={"grant": "docs"}, headers={"x-api-key": "wrong"}).status_code == 401
    body = c.get("/folder-ingest", headers=KEY).json()
    assert {"enabled", "interval_minutes", "max_files_per_cycle", "delete_removed", "auto_approve", "last_run",
            "runner", "schema_ready", "grants"} <= set(body)


def test_approve_starts_a_cycle_without_asking_the_runner_again(monkeypatch):
    c = _client(monkeypatch)
    ran = []
    monkeypatch.setattr(fi, "approve_grant", lambda g: (200, {"approved": g, "files": 4}))
    monkeypatch.setattr(fi, "run_cycle", lambda stage=True: ran.append(stage))
    r = c.post("/folder-ingest/approve", json={"grant": "docs"}, headers=KEY)
    assert r.status_code == 200 and r.json() == {"approved": "docs", "files": 4}
    assert ran == [False]


@pytest.mark.parametrize("code", [400, 404, 409, 503])
def test_approve_passes_refusals_through_and_starts_nothing(monkeypatch, code):
    c = _client(monkeypatch)
    ran = []
    monkeypatch.setattr(fi, "approve_grant", lambda g: (code, {"error": "nope"}))
    monkeypatch.setattr(fi, "run_cycle", lambda stage=True: ran.append(stage))
    r = c.post("/folder-ingest/approve", json={"grant": "docs"}, headers=KEY)
    assert r.status_code == code and r.json() == {"detail": "nope"} and ran == []
    assert c.post("/folder-ingest/approve", json={}, headers=KEY).status_code == 422


def test_the_scheduled_job_runs_one_cycle_and_never_raises(monkeypatch):
    from core import api
    calls = []
    monkeypatch.setattr(fi, "run_cycle", lambda stage=True: calls.append(stage))
    asyncio.run(api._folder_ingest_job())
    assert calls == [True]
    monkeypatch.setattr(fi, "run_cycle", lambda stage=True: (_ for _ in ()).throw(RuntimeError("x")))
    asyncio.run(api._folder_ingest_job())
