# RagLeap Core Roadmap

This roadmap tracks the honest, current state of the open-core extraction — what exists, what's in progress, and what's planned.

## Phase 1 — Foundation ✅ Complete

- [x] Public repository created
- [x] README, LICENSE, initial project structure
- [x] CONTRIBUTING.md
- [x] CODE_OF_CONDUCT.md
- [x] Issue and PR templates

## Phase 2 — Core Extraction ✅ Complete

RagLeap's production RAG engine originally lived inside a larger private Django application. This phase extracted a clean, standalone version and verified it works end-to-end, including on a genuinely fresh clone.

- [x] Identify and consolidate the core retrieval/orchestration logic (removed duplicate/legacy implementations)
- [x] Remove dependencies on private billing, multi-tenancy, and licensing code
- [x] Rewrite as a standalone module with its own minimal configuration
- [x] Vector storage and retrieval via PostgreSQL + pgvector
- [x] FastAPI web layer (`/upload`, `/chat` endpoints)
- [x] Full app Docker container (app + db via `docker compose up --build`)
- [x] Fresh-clone test — verified working from a clean `git clone` with no manual patches
- [x] Document ingestion beyond plain `.txt` (PDF, DOCX) — verified on fresh clone

## Phase 3 — Standalone Deployment Polish ✅ Complete

- [x] Working `docker compose up --build` with no external dependencies
- [x] Bring-your-own-API-key support for generation across 19 providers (OpenAI, Anthropic, Mistral, Groq, and more) — Gemini and Groq verified live end-to-end; embeddings remain Gemini-only by design (dimension constraints)
- [x] Input validation and improved error handling (file size limits, empty-input guards, question length limits, DB rollback/cleanup on ingestion failure)
- [x] Final Quickstart accuracy pass
- [x] Troubleshooting documentation for common Docker networking issues

## Phase 4 — Channels, Knowledge Graph & Integrations ✅ Complete

- [x] WhatsApp channel adapter (Twilio + Gupshup), single-tenant
- [x] Telegram channel adapter
- [x] Discord channel adapter
- [x] Voice channel — Twilio Media Streams, WebSocket server, real-time STT/TTS
- [x] Knowledge Graph (Neo4j) — entity extraction and graph-boosted retrieval alongside vector search
- [x] Language detection across all channels (~55 languages via langdetect)
- [x] Database/CRM/API integrations: MySQL, PostgreSQL, MongoDB, REST API, Salesforce, HubSpot, Shopify, Google Sheets, Stripe
- [x] Hybrid search (dense + sparse via Reciprocal Rank Fusion)
- [x] Streaming responses
- [x] Provider fallback chain
- [x] Real token usage reporting + context-size budget trimming
- [x] Web chat widget
- [x] AI Employees runtime — single-tenant, BYOK role-based agents: 9 default roles, business profile (owner-filled + auto-learned), pgvector-backed learned memory (`core/employees/`). Wired into `core/chat.py` and the `/chat`/`/chat/stream` API routes via #133.

## Phase 5 — Community (in progress)

- [ ] Public launch (Hacker News / Product Hunt)
- [ ] Open contributions with labeled good-first-issues
- [ ] Community Discord
- [ ] Plugin/extension system for custom document loaders or AI providers
## Phase 6 — `ragleap-rag` hardening (in progress)

`ragleap-rag` (the standalone PyPI library, `packages/ragleap-rag/`) went from v0.6.3 to v0.11.1 across this and prior sessions: Cost-First RAG, embedding provider expansion, structured/JSON output, query rewriting (contextual/HyDE/multi-query), removal of all hardcoded model defaults, and six vector backends (pgvector, FAISS, Pinecone, Weaviate, Qdrant, Milvus). This phase covers what's left before a confident v1.0.

- [ ] `SECURITY.md` — vulnerability disclosure process
- [ ] Dependency SBOM (`cyclonedx-bom` output) for supply-chain transparency
- [ ] CodeQL + Dependabot enabled in CI, with status badges in the README
- [ ] Real, measured benchmarks (ingestion throughput, query latency, cost per query) — run against real infrastructure and published as actually-measured numbers, not projected/estimated ones. No benchmark ships until it's been run for real; this project's whole differentiator is verified claims over marketing claims, and that standard applies here too.
- [ ] Migration guide from LangChain/LlamaIndex — real, runnable code comparisons, not just a features table
- [ ] Live verification of `PineconeBackend`, `WeaviateBackend`, `QdrantBackend`, `MilvusBackend` against real accounts (currently code-complete, verified against each SDK's actual installed source, but not run against a live service - see `packages/ragleap-rag/CHANGELOG.md` for the honest status of each)
- [ ] Embedding provider live verification: `mistral`, `together`, `cohere`, `voyage` are code-complete but not live-tested against real accounts (only `gemini`/`openai`/`ollama` are)

**Explicitly not planned for `ragleap-rag` itself**, consistent with its scope as a focused RAG library rather than a general orchestration framework: agent/tool-calling frameworks, multi-step orchestration, channel integrations (WhatsApp/Telegram/Discord/Voice - these already exist and work today in this repo's `channels/` directory, just not bundled into the `ragleap-rag` package specifically), and anything requiring a fundamentally different testing/release cadence than a retrieval library. If any of these get built as genuinely separate packages in the future, they'll be scoped and evaluated on their own merits when there's real capacity to build and verify them properly - not speculatively listed here as commitments.


## Not planned for RagLeap Core

These remain part of the commercial hosted product at [ragleap.com](https://ragleap.com), consistent with the open-core model. Note: this repo *does* include single-tenant WhatsApp/Telegram/Discord/Voice channel adapters (see Phase 4 above) — the items below are what the hosted platform adds on top of them, not duplicates of what's already open:

- Multi-tenant channel routing (this repo's channel adapters are single-tenant, one bot/config per deployment)
- Multi-tenant AI Employees orchestration — per-workspace seeding at scale (single-tenant AI Employees runtime is open in this repo, see Phase 4)
- Manager AI (executive-assistant layer with cross-channel reach)
- Persistent memory that spans sessions and channels (this repo's memory is per-conversation)
- n8n workflow automation triggered from conversations
- Multi-tenant billing and subscription management
- Observability & hallucination detection dashboard
- Managed hosting, support, and SLAs

---

This roadmap will be updated as work progresses. Contributions and feedback are welcome via [Issues](../../issues) and [Discussions](../../discussions).
