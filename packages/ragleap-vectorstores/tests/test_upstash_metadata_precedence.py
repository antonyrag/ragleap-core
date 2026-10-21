"""Mock-based tests for UpstashBackend.insert_chunk() metadata handling: no Upstash account needed. The index is
replaced by a fake that records upsert() calls."""
import pytest

pytest.importorskip("upstash_vector")

from ragleap_vectorstores.upstash_backend import UpstashBackend  # noqa: E402


class FakeIndex:
    def __init__(self):
        self.upserts = []

    def upsert(self, vectors, namespace=""):
        self.upserts.append({"vectors": vectors, "namespace": namespace})


def make_backend(tmp_path):
    backend = UpstashBackend(
        url="https://example.upstash.io", token="example-token",
        registry_path=str(tmp_path / "registry.sqlite3"),
    )
    backend._index = FakeIndex()
    return backend


def stored(backend):
    return backend._index.upserts[-1]["vectors"][0]["metadata"]


def test_caller_metadata_cannot_override_the_stored_chunk_fields(tmp_path):
    backend = make_backend(tmp_path)
    backend.insert_chunk(
        "doc1", "a.txt", 3, "real text", 7, [0.1, 0.2],
        {"text": "EVIL", "document_id": "evil", "document_name": "x", "chunk_index": 99, "token_count": 0, "page": 2},
    )
    meta = stored(backend)
    assert meta["text"] == "real text"
    assert meta["document_id"] == "doc1"
    assert meta["document_name"] == "a.txt"
    assert meta["chunk_index"] == 3
    assert meta["token_count"] == 7
    assert meta["page"] == 2


def test_extra_metadata_keys_are_kept_after_the_stored_fields_in_order(tmp_path):
    backend = make_backend(tmp_path)
    backend.insert_chunk("doc1", "a.txt", 0, "t", 1, [0.1], {"page": 1, "lang": "en", "nested": {"a": [1, 2]}})
    assert list(stored(backend)) == ["document_id", "document_name", "chunk_index", "token_count", "text", "page", "lang", "nested"]
    assert stored(backend)["nested"] == {"a": [1, 2]}


def test_missing_metadata_and_zero_token_count(tmp_path):
    backend = make_backend(tmp_path)
    backend.insert_chunk("doc1", "a.txt", 0, "t", None, [0.1], None)
    assert stored(backend) == {"document_id": "doc1", "document_name": "a.txt", "chunk_index": 0, "token_count": 0, "text": "t"}
