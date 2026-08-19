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
- [x] n8n workflow automation — single-tenant webhook triggers (`core/workflows.py`), wired into whatsapp/telegram/discord channel adapters. Voice channel not yet wired (different protocol shape). See #141.

## Phase 5 — Community (in progress)

- [ ] Public launch (Hacker News / Product Hunt)
- [x] Open contributions with labeled good-first-issues — 8+ issues labeled (help wanted / good first issue across #24-29, #134, #135), with a real external contributor actively working #134
- [ ] Community Discord
- [ ] Plugin/extension system for custom document loaders or AI providers
## Phase 6 — `ragleap-rag` hardening (in progress)

`ragleap-rag` (the standalone PyPI library, `packages/ragleap-rag/`) went from v0.6.3 to v0.12.2 across this and prior sessions: Cost-First RAG, embedding provider expansion, structured/JSON output, query rewriting (contextual/HyDE/multi-query), removal of all hardcoded model defaults, and six vector backends (pgvector, FAISS, Pinecone, Weaviate, Qdrant, Milvus). This phase covers what's left before a confident v1.0.

- [ ] `SECURITY.md` — vulnerability disclosure process
- [ ] Dependency SBOM (`cyclonedx-bom` output) for supply-chain transparency
- [ ] CodeQL + Dependabot enabled in CI, with status badges in the README
- [ ] Real, measured benchmarks (ingestion throughput, query latency, cost per query) — run against real infrastructure and published as actually-measured numbers, not projected/estimated ones. No benchmark ships until it's been run for real; this project's whole differentiator is verified claims over marketing claims, and that standard applies here too.
- [ ] Migration guide from LangChain/LlamaIndex — real, runnable code comparisons, not just a features table
- [ ] Live verification of `PineconeBackend`, `WeaviateBackend`, `QdrantBackend`, `MilvusBackend` against real accounts (currently code-complete, verified against each SDK's actual installed source, but not run against a live service - see `packages/ragleap-rag/CHANGELOG.md` for the honest status of each)
- [ ] Embedding provider live verification: `mistral`, `together`, `cohere`, `voyage` are code-complete but not live-tested against real accounts (only `gemini`/`openai`/`ollama` are)

**Explicitly not planned for `ragleap-rag` itself**, consistent with its scope as a focused RAG library rather than a general orchestration framework: agent/tool-calling frameworks, multi-step orchestration, channel integrations (WhatsApp/Telegram/Discord/Voice - these already exist and work today in this repo's `channels/` directory, just not bundled into the `ragleap-rag` package specifically), and anything requiring a fundamentally different testing/release cadence than a retrieval library. If any of these get built as genuinely separate packages in the future, they'll be scoped and evaluated on their own merits when there's real capacity to build and verify them properly - not speculatively listed here as commitments.


## Phase 7 — `ragleap-graph` hardening (in progress)

`ragleap-graph` (the standalone PyPI library, `packages/ragleap-graph/`) went from v0.1.0 to v0.6.5 across this and prior sessions: LLM-based entity/relation extraction, entity deduplication, hybrid vector+graph retrieval, per-document contribution tracking (idempotent re-upserts), lineage lookup (`find_lineage()`), and per-user data isolation (`user_id=`, with a `backfill_user_id_defaults()` migration for pre-upgrade installs). 87 tests, 86 passing, 1 skipped without `GEMINI_API_KEY`.

- [x] Core graph indexing, regex + LLM entity extraction, co-occurrence graphs
- [x] Typed relation extraction (`RELATES_AS` edges), hybrid `GraphRetriever`
- [x] Entity type support and enforcement (`entity_types=`)
- [x] Per-document idempotency for `CONTAINS`/`CO_OCCURS_WITH`/`RELATES_AS` (fixed real weight-doubling and stale-edge bugs)
- [x] `find_lineage()` — per-document contribution lookup, previously unreachable via any public method
- [x] `user_id=` for per-user data isolation across `upsert_document()` and all read methods, plus `backfill_user_id_defaults()` migration
- [ ] Audit logging (Postgres-backed, `database_url=`, writes+reads) — see [#151](../../issues/151)
- [ ] Ontology cross-validation between relation types and entity types — blocked on a design decision, see [#152](../../issues/152)
- [ ] Eval framework (graph-RAG vs vector-RAG accuracy) — new engineering, see [#153](../../issues/153)
- [ ] Cross-chunk relation extraction — see [#154](../../issues/154)

Also open: rotating a previously-exposed `GEMINI_API_KEY` ([#155](../../issues/155)), deciding how a future `ragleap-voice` package should relate to the existing `channels/voice/` code ([#156](../../issues/156)), and confirming the `/simple/` PyPI proxy serves real package data ([#157](../../issues/157)).

## Phase 8 — Ecosystem expansion (planned)

The longer-term package roadmap beyond `ragleap-rag` and `ragleap-graph`. Nothing in this phase has shipped code yet — statuses below are honest planning labels, not commitments with dates. The canonical, most-current version of this list lives in the [wiki Roadmap](https://github.com/antonyrag/ragleap-core/wiki/Roadmap); this section mirrors it for repo-local visibility.

- [ ] `ragleap-vectorstores` (NEXT) — pluggable vector backends beyond what already ships inside `ragleap-rag` core (6 backends today)
- [ ] `ragleap-tools` (NEXT) — built-in tools: search, code exec, calculators, file ops
- [ ] `ragleap-integrations` (NEXT) — MCP-native connectors + curated native integrations, building on the existing WhatsApp/Telegram/Discord/Voice channel code
- [ ] `ragleap-agents` (AFTER) — role-based crews, tool-calling, human-in-the-loop approval gates
- [ ] `ragleap-flows` (AFTER) — low-code orchestration + HITL checkpoints, bootstrapped from the existing n8n integration
- [ ] `ragleap-observability` (DECISION NEEDED) — tracing, hallucination detection, and a full LLM-as-judge evaluation framework; this is new engineering, not extraction, since nothing like the eval-framework half exists internally today
- [ ] `ragleap-ops` (ONGOING) — Docker/K8s templates, Helm charts, CI/CD, IaC; grows alongside every phase above rather than shipping as one release
- [ ] `ragleap-studio` (LATER) — visual low-code builder UI
- [ ] `ragleap-memory` (LATER) — shared long-term memory layer across agents/employees; an untracked `packages/ragleap-memory/` directory already exists from concurrent automation, not yet a scoped, owned package
- [ ] `ragleap-intelligence` (VISION / EARLY DISCUSSION ONLY) — see below

### Vision: AI Employee Twins (concept, not yet designed or built)

**The idea, in the terms it was proposed:** a Twin is tied to the *role*, not the *person*. It doesn't replace an employee — it makes them faster by holding project context, workflow knowledge, and role-specific expertise that would otherwise live only in one person's head. When someone leaves, the Twin doesn't leave with them — it becomes the trainer for whoever takes over the role, so continuity doesn't depend on a handover meeting that may or may not happen well. The stated boundary conditions, carried over unchanged from earlier discussion: **office-systems-only** (no personal-device access), **consent-based**, and **company-owned data**.

**Honest status: this is a concept, not a design.** Nothing here is scoped, nothing is built, and nothing has a version target. Before any code exists, the real open questions need real answers — not marketing language:

- **Consent mechanics** — who consents (the employee? the employer on their behalf?), to what specifically, and how is it revoked if someone changes their mind mid-employment?
- **What "role-tied" means technically** — does the Twin's learned knowledge cleanly separate from anything personal to the individual who was in the role, or does that separation turn out to be harder than it sounds once real usage data is involved?
- **Retention when a role changes hands** — what carries forward automatically vs. what requires an explicit handover step; what happens to a Twin's accumulated context if a role is eliminated entirely.
- **"Office systems only" as an actual technical boundary** — what specifically does this include and exclude, and how is that boundary enforced in code rather than just stated as a policy.
- **Labor-law and workplace-monitoring implications**, which vary by jurisdiction and are genuinely outside the scope of an engineering decision alone.

This section exists so the vision is written down honestly — ambitious, but explicitly unscoped — rather than either hidden or overclaimed. Anyone interested in helping shape the actual design (not just the code) is welcome to open a Discussion; the scoping pass above needs to happen before any implementation work starts.

## Not planned for RagLeap Core

These remain part of the commercial hosted product at [ragleap.com](https://ragleap.com), consistent with the open-core model. Note: this repo *does* include single-tenant WhatsApp/Telegram/Discord/Voice channel adapters (see Phase 4 above) — the items below are what the hosted platform adds on top of them, not duplicates of what's already open:

- Multi-tenant channel routing (this repo's channel adapters are single-tenant, one bot/config per deployment)
- Multi-tenant AI Employees orchestration — per-workspace seeding at scale (single-tenant AI Employees runtime is open in this repo, see Phase 4)
- Manager AI (executive-assistant layer with cross-channel reach) — the assistant persona itself is a real candidate to open eventually, but it's entangled with locked features (analytics, team permissions, database connections) that genuinely are SaaS-only; needs its own scoping pass before any code starts, not committed to a timeline yet
- Persistent memory that spans sessions and channels (this repo's memory is per-conversation)
- Multi-tenant n8n workflow routing (per-workspace) and Voice channel coverage (single-tenant text-channel automation is open in this repo, see Phase 4)
- Multi-tenant billing and subscription management
- Observability & hallucination detection dashboard
- Managed hosting, support, and SLAs

---

This roadmap will be updated as work progresses. Contributions and feedback are welcome via [Issues](../../issues) and [Discussions](../../discussions).
