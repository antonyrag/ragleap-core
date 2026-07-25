"""Tests for metadata_filter on ask() — JSONB containment filtering,
the multi-tenant isolation mechanism."""


def test_metadata_filter_restricts_results_to_matching_tenant(rag):
    rag.ingest_text(filename="a.txt", text="Acme tenant document about pricing.", metadata={"tenant": "acme"})
    rag.ingest_text(filename="b.txt", text="Globex tenant document about pricing.", metadata={"tenant": "globex"})

    answer = rag.ask("What is discussed about pricing?", metadata_filter={"tenant": "acme"}, hybrid=False)
    assert answer["sources"] == ["a.txt"]


def test_metadata_filter_hybrid_mode_also_respects_filter(rag):
    rag.ingest_text(filename="a.txt", text="Acme tenant document about pricing plans.", metadata={"tenant": "acme"})
    rag.ingest_text(filename="b.txt", text="Globex tenant document about pricing plans.", metadata={"tenant": "globex"})

    answer = rag.ask("pricing plans", metadata_filter={"tenant": "globex"}, hybrid=True)
    assert answer["sources"] == ["b.txt"]


def test_no_metadata_filter_returns_from_any_tenant(rag):
    rag.ingest_text(filename="a.txt", text="Acme tenant content here.", metadata={"tenant": "acme"})
    rag.ingest_text(filename="b.txt", text="Globex tenant content here.", metadata={"tenant": "globex"})

    answer = rag.ask("tenant content", hybrid=False, top_k=10)
    assert set(answer["sources"]) == {"a.txt", "b.txt"}


def test_metadata_filter_no_match_returns_empty_sources(rag):
    rag.ingest_text(filename="a.txt", text="Acme tenant content.", metadata={"tenant": "acme"})

    answer = rag.ask("tenant content", metadata_filter={"tenant": "nonexistent"}, hybrid=False)
    assert answer["sources"] == []
