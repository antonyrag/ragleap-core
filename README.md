# RagLeap Core

**The open-source AI business manager. One AI, five channels, one memory.**

RagLeap Core is the open-source engine behind RagLeap — a self-hosted RAG (retrieval-augmented generation) chat system that answers questions from your own documents, on your own server, with no vendor lock-in.

[Quickstart](#quickstart) · [Docs](https://docs.ragleap.com) · [Website](https://ragleap.com) · [Hosted Version](https://ragleap.com)

![license](https://img.shields.io/badge/license-MIT-blue) ![status](https://img.shields.io/badge/status-early--core-orange)

---

## What RagLeap Core is

RagLeap Core is a document-grounded chat engine. Upload your documents, ask questions, get cited answers — self-hosted, on your own infrastructure, with your own API key.

It is the foundation of [RagLeap](https://ragleap.com), a hosted AI business manager that adds Voice calling, WhatsApp/Telegram/Discord bots, a persistent memory system, and an executive-assistant layer on top of this same core engine.

**If RagLeap (hosted) is the business, RagLeap Core is the engine room.**

## RagLeap Core is right for you if

- ✅ You want a self-hosted RAG chatbot with full control over your data
- ✅ You want to understand exactly how document retrieval and citation works, not use a black box
- ✅ You're comfortable running your own server and your own AI provider key
- ✅ You want to contribute to or extend an open document-QA engine
- ✅ You'd rather see the code than trust a vendor's word on data privacy

## What RagLeap Core is not

| It's not... | It is... |
|---|---|
| A hosted product | Self-hosted software you run yourself |
| A multi-channel bot platform (WhatsApp/Voice/Discord) | A single-channel chat engine — those live in the hosted version |
| A no-code SaaS dashboard | A codebase you deploy and configure |
| Feature-complete with the hosted version | The foundational subset — see [Roadmap](#roadmap) |

## Features

| | |
|---|---|
| 📄 **Document ingestion** | Upload PDFs, text, and common document formats |
| 🔍 **RAG retrieval** | Vector search over your documents via pgvector |
| 💬 **Chat with citations** | Answers reference the source document, not a black box |
| 🔌 **Bring your own AI key** | OpenAI, Gemini, Anthropic, or any OpenAI-compatible endpoint |
| 🌐 **Web chat widget** | Embed a chat widget on any website |
| 🐳 **Docker-based setup** | One-command local deployment |

## What's in the hosted version (ragleap.com)

The hosted RagLeap product builds on this same core with commercial features not included here: Voice AI (real phone calls via Twilio), WhatsApp/Telegram/Discord bots, AI Employees (role-based persistent memory), Manager AI (the executive-assistant layer), n8n workflow automation, multi-tenant billing, and managed hosting with support and SLAs.

This is the standard **open-core model** — the same approach used by projects like n8n, Supabase, and Cal.com: the engine is free and open, the managed/extended product is commercial.

## Quickstart

> ⚠️ **Status: early core extraction.** This repository is in active development as we extract and clean up the core engine from RagLeap's production codebase. The commands below reflect the intended setup; if something doesn't work yet, check [open issues](../../issues) or the [Roadmap](#roadmap) below.

```bash
git clone https://github.com/antonyrag/ragleap-core.git
cd ragleap-core
cp .env.example .env
# add your AI provider key to .env
docker compose up -d
```

Requirements: Docker, Docker Compose, an API key from OpenAI, Google Gemini, or Anthropic.

## Architecture
```
                ┌─────────────────┐
                │   Web Chat UI    │
                └────────┬─────────┘
                         │
                ┌────────▼─────────┐
                │   Chat API       │
                └────────┬─────────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
 ┌────────▼───────┐ ┌────▼─────┐ ┌─────▼──────┐
 │ Document        │ │ RAG      │ │ AI Provider │
 │ Ingestion       │ │ Retrieval│ │ Adapter     │
 └────────┬────────┘ └────┬─────┘ └─────┬──────┘
          │               │              │
 ┌────────▼───────────────▼──────────────▼──────┐
 │        PostgreSQL + pgvector (embeddings)     │
 └────────────────────────────────────────────────┘

```
## Roadmap

- [x] Public repository created
- [ ] Core RAG engine extracted and cleaned from production codebase
- [ ] Standalone Docker Compose setup (no external Django project dependency)
- [ ] Document ingestion module (PDF, TXT, DOCX)
- [ ] Basic web chat widget
- [ ] Bring-your-own-API-key support (OpenAI, Gemini, Anthropic, custom endpoint)
- [ ] Contribution guide and good-first-issue labels
- [ ] Community Discord

See [ROADMAP.md](ROADMAP.md) for more detail.

## Contributing

RagLeap Core is early — the honest state right now is that we're actively extracting and cleaning the engine from a larger production codebase before it's ready for external contributions. Watch this repo or check [ROADMAP.md](ROADMAP.md) for when specific areas open up for contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) once available.

## Community

- [GitHub Issues](../../issues) — bugs and feature requests
- [GitHub Discussions](../../discussions) — ideas and questions
- [ragleap.com](https://ragleap.com) — the hosted product

## License

MIT © 2026 RagLeap
