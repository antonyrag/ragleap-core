"""
Automatic ingestion of folders the owner granted for knowledge (grants with purpose "knowledge").

The sandbox runner copies allowed documents from the read-only granted folder into a staging volume
(POST /stage on the runner). This app mounts that volume READ-ONLY and never sees a host path. Every cycle
(leader process only, see core/scheduler_leader.py) this module asks the runner to refresh the staging copies,
reads the per-grant manifest and then:
  * ingests new or changed files through the normal extract_text + ingest_document path,
  * deletes the document when its source file is gone (FOLDER_INGEST_DELETE_REMOVED, default true),
  * waits for the owner's approval before the FIRST sync of a grant, because embeddings can cost money.
Off unless FOLDER_INGEST_ENABLED=true and SANDBOX_TOKEN is set (the runner also needs COMPUTER_CONTROL=true and a
grant created with `ragleap files add ... --purpose knowledge`). Documents from folders are untrusted content,
exactly like uploads. Nothing here raises out of run_cycle(), and the model never calls this module.
"""
import hashlib
import json
import logging
import os
import re
import threading
import time

logger = logging.getLogger(__name__)

NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
MAX_REL_CHARS = 300
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_AGE = 6 * 3600       # a manifest older than this is ignored (the runner is not refreshing it)
MAX_FAILURES = 3                  # a file that failed this many times is skipped until its content changes

_lock = threading.Lock()
_failures = {}
_warned = set()
_status = {"last_run": None, "runner": None, "schema_ready": None, "grants": []}


def enabled() -> bool:
    return (os.environ.get("FOLDER_INGEST_ENABLED", "").strip().lower() == "true"
            and bool(os.environ.get("SANDBOX_TOKEN", "").strip()))


def _int_env(name, default, lo, hi):
    try:
        n = int(os.environ.get(name, "").strip())
    except ValueError:
        n = default
    return max(lo, min(hi, n))


def interval_minutes() -> int:
    return _int_env("FOLDER_INGEST_INTERVAL_MINUTES", 15, 1, 1440)


def max_files() -> int:
    return _int_env("FOLDER_INGEST_MAX_FILES", 50, 1, 500)


def delete_removed() -> bool:
    return os.environ.get("FOLDER_INGEST_DELETE_REMOVED", "true").strip().lower() not in ("false", "0", "no", "off")


def auto_approve() -> bool:
    return os.environ.get("FOLDER_INGEST_AUTO_APPROVE", "").strip().lower() == "true"


def staging_dir() -> str:
    return os.environ.get("FOLDER_INGEST_STAGING_DIR", "/staging")


# ---------------- the runner and the staging volume (everything read from there is untrusted) ----------------

def request_stage():
    """Ask the runner to refresh the staging copies. The runner's JSON answer, or None on any problem."""
    try:
        import requests
        from core import file_access
        resp = requests.post(file_access._base() + "/stage", json={}, headers=file_access._headers(),
                             timeout=150, allow_redirects=False)
        data = resp.json() if resp.status_code == 200 else None
        if not isinstance(data, dict):
            logger.warning("folder staging request answered HTTP %s", resp.status_code)
            return None
        return data
    except Exception as e:
        logger.warning("folder staging request failed: %s", type(e).__name__)
        return None


def _valid_rel(rel) -> bool:
    if not isinstance(rel, str) or not rel or len(rel) > MAX_REL_CHARS or "\x00" in rel or "\\" in rel \
            or rel.startswith("/"):
        return False
    return all(p not in ("", ".", "..") for p in rel.split("/"))


def load_manifest(grant):
    """The validated manifest of one grant, or None. Entries that fail validation are counted as invalid."""
    if not isinstance(grant, str) or not NAME_RE.fullmatch(grant):
        return None
    path = os.path.join(staging_dir(), ".manifests", grant + ".json")
    try:
        if os.path.getsize(path) > MAX_MANIFEST_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("grant") != grant or not isinstance(doc.get("files"), list):
        return None
    files, invalid = {}, 0
    for e in doc["files"]:
        size = e.get("size") if isinstance(e, dict) else None
        sha = e.get("sha256") if isinstance(e, dict) else None
        if not (isinstance(e, dict) and _valid_rel(e.get("path")) and isinstance(size, int)
                and not isinstance(size, bool) and 0 <= size <= MAX_FILE_BYTES
                and isinstance(sha, str) and SHA_RE.fullmatch(sha)):
            invalid += 1
            continue
        files[e["path"]] = {"size": size, "sha256": sha}
    skipped = doc.get("skipped") if isinstance(doc.get("skipped"), dict) else {}
    num = lambda v: v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0
    return {"grant": grant, "generated_at": num(doc.get("generated_at")), "files": files, "invalid": invalid,
            "truncated": doc.get("truncated") is True, "pending": num(doc.get("pending")),
            "unreadable": num(skipped.get("unreadable"))}


def list_manifest_grants() -> list:
    try:
        names = os.listdir(os.path.join(staging_dir(), ".manifests"))
    except OSError:
        return []
    return sorted(n[:-5] for n in names if n.endswith(".json") and NAME_RE.fullmatch(n[:-5]))


def read_staged(grant, rel, entry):
    """The bytes of one staged file, only if it is a plain file inside the grant's staging folder and its size and
    sha256 match the manifest. Otherwise None."""
    if not (NAME_RE.fullmatch(grant) and _valid_rel(rel)):
        return None
    base = os.path.realpath(os.path.join(staging_dir(), grant))
    path = os.path.join(base, *rel.split("/"))
    try:
        real = os.path.realpath(path)
        if os.path.islink(path) or not real.startswith(base + os.sep) or not os.path.isfile(real):
            return None
        with open(real, "rb") as f:
            data = f.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None
    if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        return None
    return data


# ---------------- the database ----------------

def _connect():
    from core import document_store
    return document_store._connect()


def _schema_ready() -> bool:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT (SELECT count(*) FROM information_schema.columns WHERE table_name = 'documents' "
                    "AND column_name IN ('source_grant', 'source_path', 'source_hash')), "
                    "(SELECT count(*) FROM information_schema.tables WHERE table_name = 'folder_ingest_approvals')")
        cols, tables = cur.fetchone()
        return cols == 3 and tables == 1
    finally:
        conn.close()


def _ingested(grant) -> dict:
    """{path: [(document_id, source_hash), ...]} for the documents that came from this grant."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, source_path, source_hash FROM documents WHERE source_grant = %s", (grant,))
        out = {}
        for doc_id, path, sha in cur.fetchall():
            out.setdefault(path, []).append((str(doc_id), sha))
        return out
    finally:
        conn.close()


def _approved(grant) -> bool:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM folder_ingest_approvals WHERE grant_name = %s", (grant,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def _approve(grant, files) -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO folder_ingest_approvals (grant_name, approved_files) VALUES (%s, %s) "
                    "ON CONFLICT (grant_name) DO UPDATE SET approved_at = now(), approved_files = EXCLUDED.approved_files",
                    (grant, int(files)))
        conn.commit()
    finally:
        conn.close()


def _supported(rel) -> bool:
    from core.parsers import SUPPORTED_EXTENSIONS
    return os.path.splitext(rel)[1].lower() in SUPPORTED_EXTENSIONS


def _delete_docs(ids) -> None:
    from core import document_store
    for doc_id in ids:
        try:
            if document_store.delete_document(doc_id):
                document_store.delete_document_graph(doc_id)
        except Exception as e:
            logger.warning("folder ingest: could not delete document %s: %s", doc_id, type(e).__name__)


def _ingest_file(grant, rel, entry, old_ids) -> None:
    """Ingest one staged file, then delete the documents it replaces (new first, so there is no gap)."""
    raw = read_staged(grant, rel, entry)
    if raw is None:
        raise ValueError("the staged copy is missing or changed")
    from core.ingest import ingest_document
    from core.parsers import extract_text
    text = extract_text(rel, raw)
    ingest_document(grant + "/" + rel, text, source={"grant": grant, "path": rel, "hash": entry["sha256"]})
    _delete_docs(old_ids)


# ---------------- planning and one cycle ----------------

def make_plan(manifest, ingested, supported=None) -> dict:
    """What a cycle would do for one grant. Removals are planned only when the manifest is complete: a folder that
    looks empty, or a run that hit a cap or could not read some files, must never delete documents."""
    supported = supported or _supported
    new, changed, stale, unsupported = [], [], [], 0
    for rel in sorted(manifest["files"]):
        if not supported(rel):
            unsupported += 1
            continue
        sha, docs = manifest["files"][rel]["sha256"], ingested.get(rel, [])
        current = [d for d, h in docs if h == sha]
        if not docs:
            new.append(rel)
        elif not current:
            changed.append(rel)
        else:
            stale += [d for d, h in docs if h != sha]
    complete = not (manifest["truncated"] or manifest["pending"] or manifest["unreadable"] or manifest["invalid"])
    gone = sorted(set(ingested) - set(manifest["files"])) if complete and manifest["files"] else []
    return {"new": new, "changed": changed, "stale": stale, "unsupported": unsupported,
            "removed": {rel: [d for d, _ in ingested[rel]] for rel in gone},
            "bytes_new": sum(manifest["files"][r]["size"] for r in new + changed)}


def _process_grant(grant, budget) -> dict:
    st = {"grant": grant, "state": "ok", "staged": 0, "ingested": 0, "new": 0, "changed": 0, "unsupported": 0,
          "bytes_new": 0, "done_now": 0, "removed_now": 0, "failed": 0, "waiting": 0, "truncated": False}
    manifest = load_manifest(grant)
    if manifest is None:
        st["state"] = "no_manifest"
        return st
    if time.time() - manifest["generated_at"] > MAX_MANIFEST_AGE:
        st["state"] = "stale_manifest"
        return st
    ingested = _ingested(grant)
    plan = make_plan(manifest, ingested)
    st.update(staged=len(manifest["files"]), ingested=len(ingested), new=len(plan["new"]),
              changed=len(plan["changed"]), unsupported=plan["unsupported"], bytes_new=plan["bytes_new"],
              truncated=manifest["truncated"] or manifest["pending"] > 0)
    if not ingested and not _approved(grant):
        if not auto_approve():
            st["state"] = "waiting_approval"        # the owner sees how many files and bytes will be embedded
            return st
        _approve(grant, len(manifest["files"]))
    if delete_removed():
        for ids in plan["removed"].values():
            _delete_docs(ids)
            st["removed_now"] += 1
    _delete_docs(plan["stale"])
    todo = [(rel, ingested.get(rel, [])) for rel in plan["new"] + plan["changed"]]
    for i, (rel, docs) in enumerate(todo):
        entry = manifest["files"][rel]
        key = (grant, rel, entry["sha256"])
        if _failures.get(key, 0) >= MAX_FAILURES:
            st["failed"] += 1
            continue
        if budget["left"] <= 0:
            st["waiting"] = len(todo) - i
            break
        budget["left"] -= 1
        try:
            _ingest_file(grant, rel, entry, [d for d, _ in docs])
            st["done_now"] += 1
            _failures.pop(key, None)
        except Exception as e:
            if len(_failures) > 5000:
                _failures.clear()
            _failures[key] = _failures.get(key, 0) + 1
            st["failed"] += 1
            logger.warning("folder ingest failed for %s/%s: %s", grant, rel, type(e).__name__)
    return st


def _warn_once(key, message) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message)


def run_cycle(stage=True) -> dict:
    """One pass over every staged grant. Never raises. stage=False skips asking the runner to refresh first."""
    if not enabled():
        return {"enabled": False}
    if not _lock.acquire(blocking=False):
        return {"enabled": True, "busy": True}
    try:
        if not _schema_ready():
            _warn_once("schema", "folder ingest is on but db/schema.sql has not been applied to this database")
            _status.update(schema_ready=False, grants=[])
            return {"enabled": True, "schema_ready": False}
        _status["schema_ready"] = True
        runner = None
        if stage:
            answer = request_stage()
            runner = "ok" if answer and answer.get("ok") else "error"
        budget, results = {"left": max_files()}, []
        for grant in list_manifest_grants():
            try:
                results.append(_process_grant(grant, budget))
            except Exception as e:
                logger.warning("folder ingest: grant %s failed: %s", grant, type(e).__name__)
                results.append({"grant": grant, "state": "error"})
        _status.update(last_run=int(time.time()), grants=results, **({"runner": runner} if stage else {}))
        return dict(_status, enabled=True)
    except Exception as e:
        logger.warning("folder ingest cycle failed: %s", type(e).__name__)
        return {"enabled": True, "error": "cycle failed"}
    finally:
        _lock.release()


def status() -> dict:
    """What the dashboard shows. Names, counts and sizes only, never a host path."""
    return {"enabled": enabled(), "interval_minutes": interval_minutes(), "max_files_per_cycle": max_files(),
            "delete_removed": delete_removed(), "auto_approve": auto_approve(), "last_run": _status["last_run"],
            "runner": _status["runner"], "schema_ready": _status["schema_ready"], "grants": list(_status["grants"])}


def approve_grant(grant):
    """The owner accepts the first sync of one staged grant. Returns (http_status, body)."""
    if not enabled():
        return 409, {"error": "folder ingest is off"}
    if not isinstance(grant, str) or not NAME_RE.fullmatch(grant):
        return 400, {"error": "grant must be a name"}
    manifest = load_manifest(grant)
    if manifest is None:
        return 404, {"error": "no staged folder with that name"}
    try:
        if not _schema_ready():
            return 503, {"error": "the database schema is not applied (run db/schema.sql)"}
        _approve(grant, len(manifest["files"]))
    except Exception as e:
        logger.warning("folder ingest: approval failed: %s", type(e).__name__)
        return 500, {"error": "could not record the approval"}
    return 200, {"approved": grant, "files": len(manifest["files"])}
