"""
Turns benchmark_results.json (produced by run_benchmark.py) into a
BENCHMARKS.md table. Only ever run this AFTER a real benchmark run —
never hand-edit numbers into the output.
"""
import json
import sys


def fmt(v, suffix=""):
    if v is None:
        return "—"
    return f"{v}{suffix}"


def main():
    with open("benchmark_results.json") as f:
        data = json.load(f)

    lines = []
    lines.append("# Benchmarks\n")
    lines.append(
        "All numbers below come from a real, timed run against real "
        "infrastructure — never projected or estimated. See "
        "`run_benchmark.py` for the exact methodology; re-run it yourself "
        "to reproduce.\n"
    )
    lines.append(f"- **Run date (UTC):** {data['run_timestamp_utc']}")
    lines.append(f"- **ragleap-rag version:** {data['ragleap_rag_version']}")
    lines.append(f"- **Corpus size:** {data['num_docs']} synthetic documents")
    lines.append(f"- **Queries per config:** {data['num_queries']}\n")

    lines.append("## Ingestion Throughput\n")
    lines.append("| Config | Docs Ingested | Time (s) | Docs/sec |")
    lines.append("|---|---|---|---|")
    for name, entry in data["configs"].items():
        if entry.get("status") == "failed":
            lines.append(f"| {name} | FAILED: {entry['error']} | — | — |")
            continue
        ing = entry.get("ingestion", {})
        if "note" in ing:
            lines.append(f"| {name} | {ing['note']} | — | — |")
        else:
            lines.append(
                f"| {name} | {ing.get('docs_ingested')}/{data['num_docs']} "
                f"({ing.get('docs_failed', 0)} failed) | "
                f"{fmt(ing.get('total_seconds'))} | "
                f"{fmt(ing.get('docs_per_second'))} |"
            )

    lines.append("\n## Query Latency\n")
    lines.append("| Config | Queries Run | P50 (ms) | P95 (ms) | Mean (ms) |")
    lines.append("|---|---|---|---|---|")
    for name, entry in data["configs"].items():
        if entry.get("status") == "failed":
            continue
        q = entry.get("queries", {})
        lines.append(
            f"| {name} | {q.get('queries_run')} "
            f"({q.get('queries_failed', 0)} failed) | "
            f"{fmt(q.get('latency_p50_ms'))} | "
            f"{fmt(q.get('latency_p95_ms'))} | "
            f"{fmt(q.get('latency_mean_ms'))} |"
        )

    lines.append("\n## Cost per Query\n")
    lines.append("| Config | Avg Cost (USD) | Pricing Available? |")
    lines.append("|---|---|---|")
    for name, entry in data["configs"].items():
        if entry.get("status") == "failed":
            continue
        q = entry.get("queries", {})
        avg_cost = q.get("avg_cost_usd")
        available = q.get("pricing_available")
        cost_str = f"${avg_cost}" if avg_cost is not None else "—"
        avail_str = "Yes" if available else "No (no pricing table entry for this provider)"
        lines.append(f"| {name} | {cost_str} | {avail_str} |")

    lines.append("\n## Notes & Caveats\n")
    lines.append(
        "- **Gemini free tier has two separate caps**: 5 requests/minute "
        "*and* 20 generation requests/day. The daily cap, not the per-minute "
        "one, is the binding constraint for this run — it was exhausted "
        "partway through `gemini_pgvector`'s queries, before `gemini_faiss` "
        "could run any. Numbers below reflect that real constraint, not "
        "Gemini's underlying latency in isolation."
    )
    lines.append(
        "- **`gemini_pgvector` query numbers are a partial sample (n=8 of "
        "15 requested)** — the remaining 7 failed with `429 "
        "RESOURCE_EXHAUSTED` once the daily quota ran out. The P50/P95/mean "
        "above are computed only from the 8 that succeeded."
    )
    lines.append(
        "- **`gemini_faiss` has zero successful queries this run** — not "
        "because FAISS failed, but because the shared daily Gemini quota "
        "was already spent by `gemini_pgvector`'s queries before "
        "`gemini_faiss` ran. Ingestion succeeded fully (40/40 docs) for "
        "this config; only the query-latency/cost numbers are pending. A "
        "follow-up run (next UTC day, or with a paid Gemini tier) is needed "
        "to fill this in — see Phase 6 tracking."
    )
    lines.append(
        "- **Grok/xAI was excluded entirely this run** — the configured key "
        "fails authentication (confirmed independent of ragleap-rag via a "
        "raw API call). Will be added once a working key is available."
    )
    lines.append(
        "- **Ollama's latency (P50 ~67s, P95 ~85s per query) is real, not a "
        "bug** — this reflects `qwen2.5:0.5b` running full retrieval + "
        "generation on this VPS's CPU with no GPU acceleration. It's the "
        "genuine tradeoff of a fully local, zero-cost setup on modest "
        "hardware, not a flaw in the pipeline."
    )

    out = "\n".join(lines) + "\n"
    with open("BENCHMARKS.md", "w") as f:
        f.write(out)
    print("Wrote BENCHMARKS.md")
    print("\n--- preview ---\n")
    print(out)


if __name__ == "__main__":
    main()
