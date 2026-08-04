"""
ragleap-rag real benchmark runner — Phase 6 item #4.

Measures, for real, against real infrastructure:
  1. Ingestion throughput (docs/sec)
  2. Query latency (P50 / P95, milliseconds)
  3. Cost per query (USD, where pricing data exists)

No numbers here are estimated or projected — every value in the output
JSON came from an actual timed run. If a config fails or a provider lacks
pricing data, that's recorded honestly as null/failed, not guessed.

Usage:
    export GEMINI_API_KEY="..."
    python3 run_benchmark.py

Note: Grok/xAI is intentionally excluded from this run regardless of
whether XAI_API_KEY is set — see the note in build_configs() for why.
"""
import os
import sys
import time
import json
import random
import statistics
from datetime import datetime, timezone

from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap.vectorstores import PgVectorBackend, FAISSBackend

# ---------------------------------------------------------------------------
# Config — adjust these if your environment differs
# ---------------------------------------------------------------------------
PG_DSN_MAIN = "postgresql://ragleap_test_user:ragleap_test_pass@127.0.0.1:5432/ragleap_bench_gemini"
PG_DSN_OLLAMA = "postgresql://ragleap_test_user:ragleap_test_pass@127.0.0.1:5432/ragleap_bench_ollama"
FAISS_DIR = "/tmp/ragleap_bench_faiss"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
XAI_API_KEY = os.environ.get("XAI_API_KEY")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")

GEMINI_MIN_SECONDS_BETWEEN_CALLS = 13.0

NUM_DOCS = 40
NUM_QUERIES = 15

RAGLEAP_TABLE_NAMES = ["chunks", "documents", "conversations", "conversation_messages"]


TOPICS = [
    "the Zylan trade routes",
    "Project Kestrel's power budget",
    "the Northwind harbor renovation",
    "the Aurelian tax code",
    "the Kepler-9 mining charter",
    "the Vantablack coating process",
    "the Ferrovine rail network",
    "Operation Silvermoon's logistics",
    "the Baskerville water treaty",
    "the Copperfield energy grid",
]

FACT_TEMPLATES = [
    "The annual budget for {topic} was set at {n} thousand credits in the last cycle.",
    "{topic} was first established in the year {n} according to the founding charter.",
    "A total of {n} personnel are currently assigned to oversee {topic}.",
    "The maximum capacity of {topic} is rated at {n} units per operating cycle.",
    "{topic} experienced a {n} percent increase in activity during the review period.",
]

FILLER = (
    "This section provides background context. The surrounding operational "
    "environment remains stable. Historical records indicate consistent "
    "performance across prior review cycles. Stakeholders have expressed "
    "general satisfaction with current arrangements, though minor process "
    "improvements continue to be evaluated on an ongoing basis. "
) * 6


def generate_corpus(num_docs: int, seed: int = 42):
    rng = random.Random(seed)
    docs = []
    queries = []
    for i in range(num_docs):
        topic = TOPICS[i % len(TOPICS)]
        template = FACT_TEMPLATES[i % len(FACT_TEMPLATES)]
        n = rng.randint(100, 9999)
        fact = template.format(topic=topic, n=n)
        text = f"Document {i}: Report on {topic}.\n\n{fact}\n\n{FILLER}"
        docs.append({"filename": f"doc_{i:03d}.txt", "text": text, "fact": fact, "n": n, "topic": topic})

    sample = rng.sample(docs, min(NUM_QUERIES, len(docs)))
    for d in sample:
        queries.append(f"What is the number mentioned in connection with {d['topic']}?")

    return docs, queries


def percentile(values, p):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def run_ingestion(rag, docs, pace_seconds=0.0):
    start = time.perf_counter()
    ok, failed = 0, 0
    for i, d in enumerate(docs):
        call_start = time.perf_counter()
        try:
            rag.ingest_text(filename=d["filename"], text=d["text"])
            ok += 1
        except Exception as e:
            failed += 1
            print(f"    [ingest error] {d['filename']}: {e}", file=sys.stderr)
        if (i + 1) % 10 == 0:
            print(f"    ...{i + 1}/{len(docs)} docs processed", file=sys.stderr)
        if pace_seconds > 0:
            elapsed_call = time.perf_counter() - call_start
            remaining = pace_seconds - elapsed_call
            if remaining > 0:
                time.sleep(remaining)
    elapsed = time.perf_counter() - start
    return {
        "docs_ingested": ok,
        "docs_failed": failed,
        "total_seconds": round(elapsed, 3),
        "docs_per_second": round(ok / elapsed, 3) if elapsed > 0 else None,
    }


def _answer_looks_like_failure(answer_text):
    """
    RagLeap's fallback logic can swallow a provider error internally and
    still return a 200-shaped result dict with an error message baked into
    the 'answer' text, rather than raising. A caught Python exception is not
    the only failure mode — check the answer text itself too, or broken
    providers silently produce fake-looking 'successful' latency numbers.
    """
    if not answer_text:
        return True
    lowered = answer_text.lower()
    failure_markers = [
        "incorrect api key", "invalid-argument", "error code:",
        "resource_exhausted", "quota exceeded", "authentication",
        "unauthorized", "failed to generate", "provider failed",
    ]
    return any(marker in lowered for marker in failure_markers)


def run_queries(rag, queries, pace_seconds=0.0, progress_label=""):
    latencies_ms = []
    costs = []
    pricing_available_count = 0
    errors = 0
    for i, q in enumerate(queries):
        call_start = time.perf_counter()
        try:
            result = rag.ask(q, top_k=5)
            elapsed_ms = (time.perf_counter() - call_start) * 1000

            if _answer_looks_like_failure(result.get("answer")):
                errors += 1
                print(f"    [query embedded-failure] {q!r} -> {str(result.get('answer'))[:120]}", file=sys.stderr)
            else:
                latencies_ms.append(elapsed_ms)
                cost_info = result.get("cost") or {}
                if cost_info.get("pricing_available"):
                    pricing_available_count += 1
                    if cost_info.get("cost_usd") is not None:
                        costs.append(cost_info["cost_usd"])
        except Exception as e:
            errors += 1
            print(f"    [query error] {q!r}: {e}", file=sys.stderr)

        if progress_label:
            print(f"    ...{progress_label} query {i + 1}/{len(queries)} done", file=sys.stderr)

        if pace_seconds > 0:
            elapsed_call = time.perf_counter() - call_start
            remaining = pace_seconds - elapsed_call
            if remaining > 0:
                time.sleep(remaining)

    return {
        "queries_run": len(latencies_ms),
        "queries_failed": errors,
        "latency_p50_ms": round(percentile(latencies_ms, 50), 1) if latencies_ms else None,
        "latency_p95_ms": round(percentile(latencies_ms, 95), 1) if latencies_ms else None,
        "latency_mean_ms": round(statistics.mean(latencies_ms), 1) if latencies_ms else None,
        "avg_cost_usd": round(statistics.mean(costs), 6) if costs else None,
        "pricing_available": pricing_available_count > 0,
    }


def cleanup_pg_tables(dsn):
    """
    Drop ragleap-rag's tables so a fresh init_schema() starts clean for this
    run — critical because a stale table from an earlier session (e.g. with
    the wrong embedding dimension) will silently reject every insert with a
    confusing 'expected N dimensions' error rather than a clear failure.

    Table names below were confirmed via a real \\dt against the live
    database (chunks, documents, conversations, conversation_messages) —
    not guessed or assumed from documentation.
    """
    import psycopg2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename = ANY(%s)
    """, (RAGLEAP_TABLE_NAMES,))
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        cur.execute(f'DROP TABLE IF EXISTS "{t}" CASCADE')
    cur.close()
    conn.close()
    return tables


def build_configs():
    configs = []

    if GEMINI_API_KEY:
        gemini_embedder = EmbeddingConfig(
            provider="gemini", model="models/gemini-embedding-001",
            dimensions=3072, api_key=GEMINI_API_KEY,
        )
        gemini_gen = ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key=GEMINI_API_KEY)

        configs.append({
            "name": "gemini_pgvector",
            "database_url": PG_DSN_MAIN,
            "vector_backend": None,
            "primary": gemini_gen,
            "embedder": gemini_embedder,
            "do_ingest": True,
        })

        configs.append({
            "name": "gemini_faiss",
            "database_url": PG_DSN_MAIN,
            "vector_backend": FAISSBackend(persist_directory=FAISS_DIR),
            "primary": gemini_gen,
            "embedder": gemini_embedder,
            "do_ingest": True,
        })

        if XAI_API_KEY:
            print("XAI_API_KEY is set but Grok is intentionally skipped this run "
                  "(key currently fails auth — see BENCHMARKS.md notes)", file=sys.stderr)
    else:
        print("GEMINI_API_KEY not set — skipping gemini_pgvector, gemini_faiss", file=sys.stderr)

    ollama_embedder = EmbeddingConfig(
        provider="custom", model="nomic-embed-text", dimensions=768,
        api_key="ollama", base_url=OLLAMA_BASE_URL,
    )
    ollama_gen = ProviderConfig(
        provider="custom", model="qwen2.5:0.5b", api_key="ollama",
        base_url=OLLAMA_BASE_URL,
    )
    configs.append({
        "name": "ollama_local",
        "database_url": PG_DSN_OLLAMA,
        "vector_backend": None,
        "primary": ollama_gen,
        "embedder": ollama_embedder,
        "do_ingest": True,
    })

    return configs


def main():
    docs, queries = generate_corpus(NUM_DOCS)
    configs = build_configs()

    results = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "ragleap_rag_version": __import__("ragleap").__version__,
        "num_docs": NUM_DOCS,
        "num_queries": len(queries),
        "configs": {},
    }

    for dsn in (PG_DSN_MAIN, PG_DSN_OLLAMA):
        try:
            dropped = cleanup_pg_tables(dsn)
            print(f"Cleaned {len(dropped)} existing table(s) in {dsn.split('@')[-1]}")
        except Exception as e:
            print(f"Cleanup skipped for {dsn}: {e}", file=sys.stderr)

    for cfg in configs:
        name = cfg["name"]
        print(f"\n=== {name} ===")
        try:
            rag = RagLeap(
                database_url=cfg["database_url"],
                vector_backend=cfg["vector_backend"],
                primary=cfg["primary"],
                embedder=cfg["embedder"],
            )
            rag.init_schema()

            entry = {"status": "ok"}
            is_gemini = name.startswith("gemini")
            pace = GEMINI_MIN_SECONDS_BETWEEN_CALLS if is_gemini else 0.0

            if cfg["do_ingest"]:
                print(f"  Ingesting {NUM_DOCS} docs...")
                entry["ingestion"] = run_ingestion(rag, docs)
                print(f"    -> {entry['ingestion']}")
            else:
                entry["ingestion"] = {"note": "skipped — reuses vectors from another config"}

            print(f"  Running {len(queries)} queries..."
                  + (f" (paced {pace}s apart — Gemini free-tier limit)" if pace else ""))
            entry["queries"] = run_queries(rag, queries, pace_seconds=pace, progress_label=name)
            print(f"    -> {entry['queries']}")

            results["configs"][name] = entry

        except Exception as e:
            print(f"  [FAILED] {name}: {e}", file=sys.stderr)
            results["configs"][name] = {"status": "failed", "error": str(e)}

    out_path = "benchmark_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
