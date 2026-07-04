# RagLeap Core Roadmap

This roadmap tracks the honest, current state of the open-core extraction — what exists, what's in progress, and what's planned.

## Phase 1 — Foundation (current)

- [x] Public repository created
- [x] README, LICENSE, initial project structure
- [ ] CONTRIBUTING.md
- [ ] CODE_OF_CONDUCT.md
- [ ] Issue and PR templates

## Phase 2 — Core Extraction

RagLeap's production RAG engine currently lives inside a larger private Django application. This phase extracts a clean, standalone version.

- [ ] Identify and consolidate the core retrieval/orchestration logic (removing duplicate/legacy implementations)
- [ ] Remove dependencies on private billing, multi-tenancy, and licensing code
- [ ] Rewrite as a standalone module with its own minimal configuration
- [ ] Document ingestion pipeline (PDF, TXT, DOCX, URL)
- [ ] Vector storage and retrieval via PostgreSQL + pgvector

## Phase 3 — Standalone Deployment

- [ ] Working `docker compose up` with no external dependencies
- [ ] Bring-your-own-API-key support (OpenAI, Gemini, Anthropic, custom OpenAI-compatible endpoint)
- [ ] Basic web chat widget
- [ ] Setup documentation and troubleshooting guide

## Phase 4 — Community

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
