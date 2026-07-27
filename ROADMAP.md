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

## Phase 5 — Community (in progress)

- [ ] Public launch (Hacker News / Product Hunt)
- [ ] Open contributions with labeled good-first-issues
- [ ] Community Discord
- [ ] Plugin/extension system for custom document loaders or AI providers

## Not planned for RagLeap Core

These remain part of the commercial hosted product at [ragleap.com](https://ragleap.com), consistent with the open-core model. Note: this repo *does* include single-tenant WhatsApp/Telegram/Discord/Voice channel adapters (see Phase 4 above) — the items below are what the hosted platform adds on top of them, not duplicates of what's already open:

- Multi-tenant channel routing (this repo's channel adapters are single-tenant, one bot/config per deployment)
- AI Employees (role-based persistent memory system, seeded per workspace)
- Manager AI (executive-assistant layer with cross-channel reach)
- Persistent memory that spans sessions and channels (this repo's memory is per-conversation)
- n8n workflow automation triggered from conversations
- Multi-tenant billing and subscription management
- Observability & hallucination detection dashboard
- Managed hosting, support, and SLAs

---

This roadmap will be updated as work progresses. Contributions and feedback are welcome via [Issues](../../issues) and [Discussions](../../discussions).
