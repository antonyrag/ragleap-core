"""Folder auto-ingest (core/folder_ingest.py): the manifest and staged-file checks, the plan, the first-sync approval,
changes, removals and their safety rules, the per-cycle budget and failure handling. The database and the runner
are replaced by fakes, so no Docker, network or database is used."""
import hashlib
import json
import os
import time

import pytest

from core import folder_ingest as fi


class FakeDB:
    def __init__(self):
        self.docs = {}            # id -> (grant, path, hash)
        self.approved = set()
        self.ingest_calls = []
        self.deleted = []
        self.fail_paths = set()
        self.n = 0

    def ingested(self, grant):
        out = {}
        for doc_id, (g, p, h) in self.docs.items():
            if g == grant:
                out.setdefault(p, []).append((doc_id, h))
        return out

    def ingest_file(self, grant, rel, entry, old_ids):
        self.ingest_calls.append((grant, rel))
        if rel in self.fail_paths:
            raise ValueError("boom")
        self.n += 1
        self.docs["d%d" % self.n] = (grant, rel, entry["sha256"])
        self.delete_docs(old_ids)

    def delete_docs(self, ids):
        for i in ids:
            self.docs.pop(i, None)
            self.deleted.append(i)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FOLDER_INGEST_ENABLED", "true")
    monkeypatch.setenv("SANDBOX_TOKEN", "tok")
    monkeypatch.setenv("FOLDER_INGEST_STAGING_DIR", str(tmp_path))
    db = FakeDB()
    monkeypatch.setattr(fi, "_schema_ready", lambda: True)
    monkeypatch.setattr(fi, "_ingested", db.ingested)
    monkeypatch.setattr(fi, "_approved", lambda g: g in db.approved)
    monkeypatch.setattr(fi, "_approve", lambda g, n: db.approved.add(g))
    monkeypatch.setattr(fi, "_ingest_file", db.ingest_file)
    monkeypatch.setattr(fi, "_delete_docs", db.delete_docs)
    monkeypatch.setattr(fi, "_supported", lambda rel: not rel.endswith(".xyz"))
    monkeypatch.setattr(fi, "request_stage", lambda: {"ok": True})
    fi._failures.clear()
    fi._status.update(last_run=None, runner=None, schema_ready=None, grants=[])
    return tmp_path, db


def put(root, grant, files, generated_at=None, **extra):
    """Write staged files and a manifest the way the runner's copier does."""
    entries = []
    for rel, data in files.items():
        p = root / grant / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        entries.append({"path": rel, "size": len(data), "mtime": 1, "sha256": hashlib.sha256(data).hexdigest()})
    (root / ".manifests").mkdir(exist_ok=True)
    doc = {"grant": grant, "generated_at": int(generated_at or time.time()), "files": entries,
           "skipped": {"unreadable": extra.pop("unreadable", 0)}, "pending": extra.pop("pending", 0),
           "truncated": extra.pop("truncated", False)}
    (root / ".manifests" / (grant + ".json")).write_text(json.dumps(doc))
    return entries


def grant_state(result, grant="docs"):
    return [g for g in result["grants"] if g["grant"] == grant][0]


# ---------------- switches ----------------

def test_off_by_default_and_needs_the_runner_token(monkeypatch):
    for name in ("FOLDER_INGEST_ENABLED", "SANDBOX_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert fi.enabled() is False and fi.run_cycle() == {"enabled": False}
    monkeypatch.setenv("FOLDER_INGEST_ENABLED", "true")
    assert fi.enabled() is False                                  # no SANDBOX_TOKEN
    monkeypatch.setenv("SANDBOX_TOKEN", "tok")
    assert fi.enabled() is True
    monkeypatch.setenv("FOLDER_INGEST_ENABLED", "yes")
    assert fi.enabled() is False                                  # only the literal "true"


def test_settings_have_safe_defaults_and_limits(monkeypatch):
    for n in ("FOLDER_INGEST_INTERVAL_MINUTES", "FOLDER_INGEST_MAX_FILES", "FOLDER_INGEST_DELETE_REMOVED",
              "FOLDER_INGEST_AUTO_APPROVE"):
        monkeypatch.delenv(n, raising=False)
    assert (fi.interval_minutes(), fi.max_files(), fi.delete_removed(), fi.auto_approve()) == (15, 50, True, False)
    monkeypatch.setenv("FOLDER_INGEST_INTERVAL_MINUTES", "0")
    monkeypatch.setenv("FOLDER_INGEST_MAX_FILES", "99999")
    monkeypatch.setenv("FOLDER_INGEST_DELETE_REMOVED", "off")
    assert (fi.interval_minutes(), fi.max_files(), fi.delete_removed()) == (1, 500, False)
    monkeypatch.setenv("FOLDER_INGEST_MAX_FILES", "abc")
    assert fi.max_files() == 50


# ---------------- what is read from the staging volume is untrusted ----------------

def test_manifest_entries_are_validated(env):
    root, _ = env
    good = {"path": "a.txt", "size": 3, "mtime": 1, "sha256": "a" * 64}
    bad = [{"path": "/etc/passwd", "size": 1, "sha256": "a" * 64}, {"path": "../x.txt", "size": 1, "sha256": "a" * 64},
           {"path": "a\\b.txt", "size": 1, "sha256": "a" * 64}, {"path": "x/../y.txt", "size": 1, "sha256": "a" * 64},
           {"path": "b.txt", "size": 1, "sha256": "nothex"}, {"path": "c.txt", "size": -1, "sha256": "a" * 64},
           {"path": "d.txt", "size": 10 ** 9, "sha256": "a" * 64}, {"path": "e.txt", "size": True, "sha256": "a" * 64},
           "junk", None]
    (root / ".manifests").mkdir()
    (root / ".manifests" / "docs.json").write_text(json.dumps({"grant": "docs", "files": [good] + bad}))
    m = fi.load_manifest("docs")
    assert list(m["files"]) == ["a.txt"] and m["invalid"] == len(bad)


@pytest.mark.parametrize("content", ["not json", "[]", json.dumps({"grant": "other", "files": []}),
                                     json.dumps({"grant": "docs", "files": "nope"})])
def test_a_bad_manifest_is_ignored(env, content):
    root, _ = env
    (root / ".manifests").mkdir()
    (root / ".manifests" / "docs.json").write_text(content)
    assert fi.load_manifest("docs") is None


def test_grant_names_are_checked_before_any_path_is_built(env):
    root, _ = env
    assert fi.load_manifest("../docs") is None and fi.load_manifest("Docs") is None and fi.load_manifest(5) is None
    put(root, "docs", {"a.txt": b"x"})
    (root / ".manifests" / "..evil.json").write_text("{}")
    (root / ".manifests" / "Bad Name.json").write_text("{}")
    assert fi.list_manifest_grants() == ["docs"]


def test_a_staged_file_must_match_the_manifest_exactly(env):
    root, _ = env
    entry = put(root, "docs", {"sub/a.txt": b"hello"})[0]
    e = {"size": entry["size"], "sha256": entry["sha256"]}
    assert fi.read_staged("docs", "sub/a.txt", e) == b"hello"
    assert fi.read_staged("docs", "sub/a.txt", dict(e, sha256="0" * 64)) is None      # content differs
    assert fi.read_staged("docs", "sub/a.txt", dict(e, size=9)) is None
    assert fi.read_staged("docs", "missing.txt", e) is None
    assert fi.read_staged("docs", "../docs/sub/a.txt", e) is None and fi.read_staged("../docs", "sub/a.txt", e) is None


def test_a_symlink_in_staging_is_never_followed(env, tmp_path_factory):
    root, _ = env
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_bytes(b"SECRET")
    entry = put(root, "docs", {"a.txt": b"SECRET"})[0]
    (root / "docs" / "a.txt").unlink()
    os.symlink(outside, root / "docs" / "a.txt")
    assert fi.read_staged("docs", "a.txt", {"size": 6, "sha256": entry["sha256"]}) is None
    (root / "docs" / "sub").mkdir()
    os.symlink(outside.parent, root / "docs" / "dirlink")
    assert fi.read_staged("docs", "dirlink/secret.txt", {"size": 6, "sha256": entry["sha256"]}) is None


# ---------------- the plan ----------------

def manifest_of(files, **kw):
    return dict({"grant": "g", "generated_at": 0, "invalid": 0, "truncated": False, "pending": 0, "unreadable": 0,
                 "files": {p: {"size": 1, "sha256": s * 64} for p, s in files.items()}}, **kw)


def test_plan_sorts_files_into_new_changed_stale_and_unsupported(env):
    m = manifest_of({"new.txt": "a", "same.txt": "b", "chg.txt": "c", "dup.txt": "d", "x.xyz": "e"})
    have = {"same.txt": [("1", "b" * 64)], "chg.txt": [("2", "0" * 64)],
            "dup.txt": [("3", "d" * 64), ("4", "0" * 64)], "gone.txt": [("5", "f" * 64)]}
    p = fi.make_plan(m, have)
    assert p["new"] == ["new.txt"] and p["changed"] == ["chg.txt"] and p["stale"] == ["4"]
    assert p["unsupported"] == 1 and p["removed"] == {"gone.txt": ["5"]}


@pytest.mark.parametrize("flag", [{"truncated": True}, {"pending": 3}, {"unreadable": 1}, {"invalid": 1}])
def test_an_incomplete_manifest_never_plans_removals(flag):
    p = fi.make_plan(manifest_of({"a.txt": "a"}, **flag), {"old.txt": [("1", "f" * 64)]})
    assert p["removed"] == {}


def test_an_empty_manifest_never_plans_removals():
    assert fi.make_plan(manifest_of({}), {"old.txt": [("1", "f" * 64)]})["removed"] == {}


# ---------------- cycles ----------------

def test_the_first_sync_waits_for_the_owner_and_shows_what_it_will_embed(env):
    root, db = env
    put(root, "docs", {"a.txt": b"aaaa", "b.md": b"bb"})
    s = grant_state(fi.run_cycle())
    assert s["state"] == "waiting_approval" and s["new"] == 2 and s["bytes_new"] == 6 and s["staged"] == 2
    assert db.ingest_calls == [] and db.docs == {}
    assert fi.approve_grant("docs") == (200, {"approved": "docs", "files": 2})
    s = grant_state(fi.run_cycle(stage=False))
    assert s["state"] == "ok" and s["done_now"] == 2 and sorted(c[1] for c in db.ingest_calls) == ["a.txt", "b.md"]


def test_auto_approve_skips_the_wait_and_records_it(env, monkeypatch):
    root, db = env
    monkeypatch.setenv("FOLDER_INGEST_AUTO_APPROVE", "true")
    put(root, "docs", {"a.txt": b"a"})
    assert grant_state(fi.run_cycle())["done_now"] == 1 and "docs" in db.approved


def approved_with(env, files, **kw):
    root, db = env
    db.approved.add("docs")
    put(root, "docs", files, **kw)
    return root, db


def test_unchanged_files_are_not_ingested_again_and_changes_replace_the_document(env):
    root, db = approved_with(env, {"a.txt": b"one", "b.txt": b"two"})
    assert grant_state(fi.run_cycle())["done_now"] == 2
    assert grant_state(fi.run_cycle())["done_now"] == 0 and len(db.ingest_calls) == 2
    put(root, "docs", {"a.txt": b"one CHANGED", "b.txt": b"two"})
    s = grant_state(fi.run_cycle())
    assert s["done_now"] == 1 and len(db.docs) == 2 and len(db.deleted) == 1
    assert sorted(h for _, _, h in db.docs.values()) == sorted(
        hashlib.sha256(x).hexdigest() for x in (b"one CHANGED", b"two"))


def test_a_removed_source_file_removes_its_document_unless_that_is_switched_off(env, monkeypatch):
    root, db = approved_with(env, {"a.txt": b"one", "b.txt": b"two"})
    fi.run_cycle()
    put(root, "docs", {"a.txt": b"one"})
    monkeypatch.setenv("FOLDER_INGEST_DELETE_REMOVED", "false")
    assert grant_state(fi.run_cycle())["removed_now"] == 0 and len(db.docs) == 2
    monkeypatch.setenv("FOLDER_INGEST_DELETE_REMOVED", "true")
    assert grant_state(fi.run_cycle())["removed_now"] == 1
    assert [p for _, p, _ in db.docs.values()] == ["a.txt"]


@pytest.mark.parametrize("what", ["empty", "truncated", "pending", "unreadable", "stale"])
def test_nothing_is_deleted_when_the_manifest_cannot_be_trusted(env, what):
    root, db = approved_with(env, {"a.txt": b"one", "b.txt": b"two"})
    fi.run_cycle()
    assert len(db.docs) == 2
    kw = {"truncated": what == "truncated", "pending": 2 if what == "pending" else 0,
          "unreadable": 1 if what == "unreadable" else 0,
          "generated_at": time.time() - 7 * 3600 if what == "stale" else None}
    put(root, "docs", {} if what == "empty" else {"a.txt": b"one"}, **kw)
    s = grant_state(fi.run_cycle())
    assert db.deleted == [] and len(db.docs) == 2, s
    assert (s["state"] == "stale_manifest") == (what == "stale")


def test_the_per_cycle_budget_spreads_a_big_folder_over_several_cycles(env, monkeypatch):
    root, db = approved_with(env, {"f%d.txt" % i: b"x%d" % i for i in range(5)})
    monkeypatch.setenv("FOLDER_INGEST_MAX_FILES", "2")
    s = grant_state(fi.run_cycle())
    assert s["done_now"] == 2 and s["waiting"] == 3
    assert [grant_state(fi.run_cycle())["done_now"] for _ in range(2)] == [2, 1]
    assert len(db.docs) == 5 and grant_state(fi.run_cycle())["waiting"] == 0


def test_the_budget_is_shared_between_grants(env, monkeypatch):
    root, db = env
    db.approved.update({"docs", "kb2"})
    put(root, "docs", {"a.txt": b"1", "b.txt": b"2"})
    put(root, "kb2", {"c.txt": b"3", "d.txt": b"4"})
    monkeypatch.setenv("FOLDER_INGEST_MAX_FILES", "3")
    r = fi.run_cycle()
    assert grant_state(r, "docs")["done_now"] == 2 and grant_state(r, "kb2")["done_now"] == 1
    assert grant_state(r, "kb2")["waiting"] == 1


def test_a_failing_file_is_retried_a_few_times_and_then_left_alone_until_it_changes(env):
    root, db = approved_with(env, {"bad.txt": b"x", "ok.txt": b"y"})
    db.fail_paths.add("bad.txt")
    for _ in range(fi.MAX_FAILURES):
        assert grant_state(fi.run_cycle())["failed"] == 1
    calls = len(db.ingest_calls)
    s = grant_state(fi.run_cycle())
    assert s["failed"] == 1 and len(db.ingest_calls) == calls                  # skipped, not retried
    assert [p for _, p, _ in db.docs.values()] == ["ok.txt"]
    db.fail_paths.clear()
    put(root, "docs", {"bad.txt": b"x fixed", "ok.txt": b"y"})
    assert grant_state(fi.run_cycle())["done_now"] == 1                        # new content, new chance


def test_one_broken_grant_does_not_stop_the_others(env, monkeypatch):
    root, db = env
    db.approved.update({"docs", "kb2"})
    put(root, "docs", {"a.txt": b"1"})
    put(root, "kb2", {"b.txt": b"2"})
    real = fi._process_grant
    monkeypatch.setattr(fi, "_process_grant", lambda g, b: (_ for _ in ()).throw(RuntimeError("x")) if g == "docs" else real(g, b))
    r = fi.run_cycle()
    assert grant_state(r, "docs")["state"] == "error" and grant_state(r, "kb2")["done_now"] == 1


def test_a_cycle_asks_the_runner_first_unless_told_not_to(env, monkeypatch):
    root, db = approved_with(env, {"a.txt": b"1"})
    asked = []
    monkeypatch.setattr(fi, "request_stage", lambda: asked.append(1) or {"ok": True})
    assert fi.run_cycle()["runner"] == "ok" and asked == [1]
    fi.run_cycle(stage=False)
    assert asked == [1]
    monkeypatch.setattr(fi, "request_stage", lambda: None)
    assert fi.run_cycle()["runner"] == "error"


def test_a_database_without_the_new_columns_is_left_alone(env, monkeypatch):
    root, db = approved_with(env, {"a.txt": b"1"})
    monkeypatch.setattr(fi, "_schema_ready", lambda: False)
    assert fi.run_cycle() == {"enabled": True, "schema_ready": False} and db.ingest_calls == []
    assert fi.approve_grant("docs")[0] == 503


def test_run_cycle_never_raises_and_does_not_overlap(env, monkeypatch):
    monkeypatch.setattr(fi, "_schema_ready", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert fi.run_cycle() == {"enabled": True, "error": "cycle failed"}
    assert fi._lock.acquire(blocking=False)
    try:
        assert fi.run_cycle() == {"enabled": True, "busy": True}
    finally:
        fi._lock.release()


# ---------------- approval, status, the runner call ----------------

def test_approve_checks_its_input(env, monkeypatch):
    root, db = env
    assert fi.approve_grant("../x")[0] == 400 and fi.approve_grant(5)[0] == 400
    assert fi.approve_grant("docs")[0] == 404                                  # nothing staged under that name
    put(root, "docs", {"a.txt": b"1"})
    assert fi.approve_grant("docs") == (200, {"approved": "docs", "files": 1}) and "docs" in db.approved
    monkeypatch.delenv("FOLDER_INGEST_ENABLED")
    assert fi.approve_grant("docs")[0] == 409


def test_status_shows_names_counts_and_sizes_only(env):
    root, db = env
    put(root, "docs", {"a.txt": b"1234"})
    fi.run_cycle()
    s = fi.status()
    assert s["enabled"] is True and s["interval_minutes"] == 15 and s["runner"] == "ok" and s["last_run"]
    assert s["grants"][0]["state"] == "waiting_approval" and s["grants"][0]["bytes_new"] == 4
    assert str(root) not in json.dumps(s)


def test_request_stage_posts_nothing_but_an_empty_body_with_the_token(monkeypatch):
    monkeypatch.setenv("SANDBOX_TOKEN", "tok")
    monkeypatch.setenv("SANDBOX_URL", "http://runner:8099")
    sent = {}

    class Resp:
        status_code = 200
        def json(self):
            return {"ok": True, "results": []}

    def fake_post(url, **kw):
        sent.update(url=url, **kw)
        return Resp()

    monkeypatch.setattr("requests.post", fake_post)
    assert fi.request_stage() == {"ok": True, "results": []}
    assert sent["url"] == "http://runner:8099/stage" and sent["json"] == {} and sent["allow_redirects"] is False
    assert sent["headers"] == {"Authorization": "Bearer tok"}
    monkeypatch.setattr("requests.post", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert fi.request_stage() is None


# ---------------- _ingest_file with the real ingest and parser calls replaced ----------------

def test_ingest_file_ingests_first_then_deletes_the_old_documents(tmp_path, monkeypatch):
    monkeypatch.setenv("FOLDER_INGEST_STAGING_DIR", str(tmp_path))
    entry = put(tmp_path, "docs", {"sub/a.txt": b"hello"})[0]
    e = {"size": entry["size"], "sha256": entry["sha256"]}
    calls = []
    monkeypatch.setattr("core.parsers.extract_text", lambda name, raw: calls.append(("extract", name, raw)) or "TEXT")
    monkeypatch.setattr("core.ingest.ingest_document",
                        lambda name, text, source=None: calls.append(("ingest", name, text, source)))
    monkeypatch.setattr("core.document_store.delete_document", lambda i: calls.append(("delete", i)) or True)
    monkeypatch.setattr("core.document_store.delete_document_graph", lambda i: calls.append(("graph", i)) or "cleaned")
    fi._ingest_file("docs", "sub/a.txt", e, ["old1", "old2"])
    assert calls == [("extract", "sub/a.txt", b"hello"),
                     ("ingest", "docs/sub/a.txt", "TEXT", {"grant": "docs", "path": "sub/a.txt", "hash": entry["sha256"]}),
                     ("delete", "old1"), ("graph", "old1"), ("delete", "old2"), ("graph", "old2")]
    calls.clear()
    with pytest.raises(ValueError):
        fi._ingest_file("docs", "sub/a.txt", dict(e, sha256="0" * 64), ["old1"])       # the staged copy changed
    assert calls == []                                                                  # nothing ingested, nothing deleted
