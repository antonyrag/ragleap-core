# RagLeap Core

**The open-source AI business manager. One AI, five channels, one memory.**

RagLeap Core is the open-source engine behind RagLeap — a self-hosted RAG (retrieval-augmented generation) chat system that answers questions from your own documents, on your own server, with no vendor lock-in.

[Quickstart](#quickstart) · [Docs](https://docs.ragleap.com) · [Website](https://ragleap.com) · [Hosted Version](https://ragleap.com)

![license](https://img.shields.io/badge/license-MIT-blue) ![status](https://img.shields.io/badge/status-early--core-orange)

---

## If a RAG chatbot answers questions, RagLeap runs your business

Most open-source RAG projects give you a toolkit — you still have to build the app, wire up a UI, add memory, and connect every channel yourself. RagLeap Core gives you a working chat engine out of the box, and the full RagLeap platform turns it into an AI that actually operates a business.

| Without RagLeap | With RagLeap |
|---|---|
| ❌ A different bot for your website, WhatsApp, and Telegram — none of them share memory | ✅ One AI across every channel, with memory that persists between them |
| ❌ Your RAG chatbot forgets everything the moment a session ends | ✅ Persistent memory — facts and preferences carry across sessions and channels |
| ❌ You're a developer, so you can wire up LangChain — but your team can't manage it | ✅ A real dashboard for non-technical owners: settings, analytics, team, billing |
| ❌ Answering customer questions and running the business are two separate systems | ✅ Manager AI — an executive assistant that can see analytics, send emails, and manage settings by conversation |
| ❌ Adding a phone line means integrating Twilio, STT, and TTS yourself | ✅ Voice AI is built in — real inbound calls, answered and routed automatically |
| ❌ Automating a workflow means writing custom code per integration | ✅ n8n workflow automation triggered directly from any conversation |

## What makes RagLeap Core specifically different

This repo isn't a general-purpose RAG framework you assemble into something — it's the real, working engine that already powers a production AI business platform (see [What's in the hosted version](#whats-in-the-hosted-version-ragleapcom) below). The code here is honest about being early, but it's extracted from something that already works in the real world, not built as a demo.

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
## Architecture

RagLeap Core is the foundation layer of the full RagLeap platform. Here's how it fits into the bigger picture:

```
                    +---------------------------------------------------------+
                    |              RagLeap (Hosted Platform)                    |
                    |                                                            |
                    |  [locked] Manager AI - private executive assistant        |
                    |  [locked] AI Employees - role-based persistent memory     |
                    |  [locked] Voice AI - real phone calls via Twilio          |
                    |  [locked] WhatsApp / Telegram / Discord bots              |
                    |  [locked] n8n Workflow Automation                         |
                    |  [locked] Persistent Memory (cross-channel, cross-session)|
                    |  [locked] 222+ Language auto-detection, all channels      |
                    |  [locked] Multi-tenant Billing, Teams & Permissions       |
                    |  [locked] Audit History / Compliance logging              |
                    |  [locked] Embed Widget Control Center (white-label)       |
                    |  [locked] Managed hosting, backups, SLA, support          |
                    |                                                            |
                    |                 built on top of                          |
                    +---------------------------------------------------------+
                                              |
                    +-----------------------------------------------------+
                    |            RagLeap Core (this repo, open)            |
                    |                                                       |
                    |   +-----------------+                                 |
                    |   |   Web Chat UI    |                                 |
                    |   +--------+---------+                                 |
                    |            |                                           |
                    |   +--------v---------+                                 |
                    |   |   Chat API       |                                 |
                    |   +--------+---------+                                 |
                    |            |                                           |
                    |  +----------+----------+                               |
                    |  |          |          |                               |
                    | +v--------+ +v-------+ +v----------+                   |
                    | |Document | |  RAG   | |AI Provider|                   |
                    | |Ingest   | |Retrieve| |  Adapter  |                   |
                    | +----+----+ +---+----+ +-----+-----+                   |
                    |      |          |            |                         |
                    |  +----v----------v------------v---+                    |
                    |  |  PostgreSQL + pgvector          |                    |
                    |  +---------------------------------+                    |
                    +-------------------------------------------------------+
```

**[locked]** = commercial/hosted-only feature, not included in this repository. See below for the full breakdown.

## What's in the hosted version (ragleap.com)

RagLeap Core covers document upload, retrieval, and web chat. The hosted platform builds a full AI business manager on top of it:

| Area | What it adds |
|---|---|
| **Manager AI** | A private executive assistant for the owner — sees documents, analytics, team permissions, and database connections; can send emails, generate reports, and manage settings by conversation, reachable via Web, WhatsApp, Telegram, or phone call |
| **AI Employees** | Specialized AI roles seeded per workspace, each with its own permanent memory, so support and sales conversations draw on different context automatically |
| **Voice AI** | Real inbound phone calls via Twilio — speech-to-text, RAG-grounded response, text-to-speech, with owner vs. customer call routing |
| **Multi-channel bots** | WhatsApp (Twilio or Gupshup), Telegram, and Discord bots, all backed by the same document knowledge base |
| **Persistent Memory** | Facts and preferences that persist across sessions and channels, not just within a single conversation |
| **Advanced AI Settings** | Model selection (Gemini/OpenAI/Claude), temperature tuning, bring-your-own-key per provider, and automatic failover across a fallback key pool |
| **Team Chat** | Internal team messaging board per workspace, separate from customer-facing AI chat |
| **n8n Workflows** | Trigger no-code automations directly from a conversation, across every channel |
| **222+ Languages** | Auto-detected per user, applied consistently across every channel |
| **Neo4j Knowledge Graph** | Hybrid graph + vector retrieval for richer, more connected answers — available on the hosted platform |
| **Integrations & Database Connectors** | Connect existing business tools and external databases, with AI-suggested automations per channel and developer-level custom automations |
| **Analytics Dashboard** | Per-provider usage breakdown (OpenAI, Gemini, Claude), query volume, token costs, and daily trends |
| **Team & Billing** | Multi-tenant workspaces, team member permissions, subscription plans, usage-based billing |
| **Audit History** | Full log of configuration changes — who changed what, and when |
| **Embed Control Center** | White-label widget builder — Bubble, Fixed Panel, or Full Page embeds for any website |
| **Data Visibility Controls** | Per-document and per-database Public/Private settings — control exactly what customer-facing bots see vs. what's reserved for Manager AI only |
| **Observability & Hallucination Detection** | Built-in monitoring layer that audits AI responses for accuracy and flags potential hallucinations |
| **Cloud or Self-Hosted deployment** | Run the full platform as managed cloud (subscription) or self-hosted on your own server (one-time license) |
| **Managed hosting** | Backups, uptime SLA, and support — zero infrastructure to maintain |

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
