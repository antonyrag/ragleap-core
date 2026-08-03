# Benchmarks

All numbers below come from a real, timed run against real infrastructure — never projected or estimated. See `run_benchmark.py` for the exact methodology; re-run it yourself to reproduce.

- **Run date (UTC):** 2026-08-03T09:39:09.302714+00:00
- **ragleap-rag version:** 0.11.1
- **Corpus size:** 40 synthetic documents
- **Queries per config:** 15

## Ingestion Throughput

| Config | Docs Ingested | Time (s) | Docs/sec |
|---|---|---|---|
| gemini_pgvector | 40/40 (0 failed) | 36.275 | 1.103 |
| gemini_faiss | 40/40 (0 failed) | 35.372 | 1.131 |
| ollama_local | 40/40 (0 failed) | 112.742 | 0.355 |

## Query Latency

| Config | Queries Run | P50 (ms) | P95 (ms) | Mean (ms) |
|---|---|---|---|---|
| gemini_pgvector | 8 (7 failed) | 3934.4 | 6529.9 | 4253.0 |
| gemini_faiss | 0 (15 failed) | — | — | — |
| ollama_local | 15 (0 failed) | 67028.3 | 84883.4 | 47243.8 |

## Cost per Query

| Config | Avg Cost (USD) | Pricing Available? |
|---|---|---|
| gemini_pgvector | $0.003346 | Yes |
| gemini_faiss | — | No (no pricing table entry for this provider) |
| ollama_local | — | No (no pricing table entry for this provider) |

## Notes & Caveats

- **Gemini free tier has two separate caps**: 5 requests/minute *and* 20 generation requests/day. The daily cap, not the per-minute one, is the binding constraint for this run — it was exhausted partway through `gemini_pgvector`'s queries, before `gemini_faiss` could run any. Numbers below reflect that real constraint, not Gemini's underlying latency in isolation.
- **`gemini_pgvector` query numbers are a partial sample (n=8 of 15 requested)** — the remaining 7 failed with `429 RESOURCE_EXHAUSTED` once the daily quota ran out. The P50/P95/mean above are computed only from the 8 that succeeded.
- **`gemini_faiss` has zero successful queries this run** — not because FAISS failed, but because the shared daily Gemini quota was already spent by `gemini_pgvector`'s queries before `gemini_faiss` ran. Ingestion succeeded fully (40/40 docs) for this config; only the query-latency/cost numbers are pending. A follow-up run (next UTC day, or with a paid Gemini tier) is needed to fill this in — see Phase 6 tracking.
- **Grok/xAI was excluded entirely this run** — the configured key fails authentication (confirmed independent of ragleap-rag via a raw API call). Will be added once a working key is available.
- **Ollama's latency (P50 ~67s, P95 ~85s per query) is real, not a bug** — this reflects `qwen2.5:0.5b` running full retrieval + generation on this VPS's CPU with no GPU acceleration. It's the genuine tradeoff of a fully local, zero-cost setup on modest hardware, not a flaw in the pipeline.
