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
- [ ] Document ingestion beyond plain `.txt` (PDF, DOCX)

## Phase 3 — Standalone Deployment Polish

- [x] Working `docker compose up --build` with no external dependencies
- [ ] Bring-your-own-API-key support for additional providers (OpenAI, Anthropic) — Gemini-only currently, by design
- [ ] Input validation and improved error handling
- [ ] Final Quickstart accuracy pass

## Phase 4 — Community

- [ ] Public launch (Hacker News / Product Hunt) — deferred until Phase 2/3 polish is fully done
- [ ] Open contributions with labeled good-first-issues
- [ ] Community Discord
- [ ] Plugin/extension system for custom document loaders or AI providers

## Not planned for RagLeap Core

These remain part of the commercial hosted product at [ragleap.com](https://ragleap.com), consistent with the open-core model:

- Voice AI / phone call handling
- WhatsApp, Telegram, Discord bot integrations
- AI Employees (role-based persistent memory system)
- Manager AI (executive-assistant layer)
- n8n workflow automation
- Multi-tenant billing and subscription management
- Managed hosting, support, and SLAs

---

This roadmap will be updated as work progresses. Contributions and feedback are welcome via [Issues](../../issues) and [Discussions](../../discussions).
