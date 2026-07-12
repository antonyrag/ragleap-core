# Contributing to RagLeap Core

Thanks for your interest in contributing! Here's where things actually stand
and how to get started.

## Where things stand

RagLeap Core is a working, tested self-hosted RAG engine with document
ingestion, retrieval, generation, and WhatsApp/Telegram/Discord/Voice
channel adapters — all verified end-to-end. Every change goes through CI
(compile check + a real Docker build + smoke test), so contributions are
welcome now, not "someday."

Check the [good first issue](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
label for scoped, approachable tasks, or
[help wanted](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22)
for things that need investigation or specific API access to test.

## How to contribute code

1. Fork the repo and clone your fork
2. Create a branch: `git checkout -b feat/your-change` (or `fix/`, `docs/`)
3. Make your change
4. Test it locally: `docker compose up --build -d`, then verify with a real
   request (`curl http://localhost:8000/health`, or whatever your change
   affects)
5. Open a Pull Request — CI will run automatically (compile check + Docker
   build + smoke test)
6. Once checks pass, a maintainer will review and merge

Small, focused PRs are much easier to review than large ones — if your
change touches multiple unrelated things, consider splitting it up.

## Code style

- Python, PEP 8-ish (not strictly enforced yet, but keep it readable)
- Clear commit messages: `feat: ...`, `fix: ...`, `docs: ...` prefixes are
  used throughout the existing history — following that pattern helps
- Add a brief docstring to new functions, especially anything with
  non-obvious behavior (see `channels/*/router.py` for examples)

## Reporting bugs

Open an [Issue](../../issues) with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your environment (OS, Docker version, `LLM_PROVIDER` if relevant)

## Adding a new BYOK provider or channel

If you're adding support for a new LLM provider or messaging channel,
look at the existing pattern first:
- LLM providers: `core/generation.py`'s `PROVIDER_BASE_URLS` dict and
  `GenerationService` class
- Channels: `channels/whatsapp/`, `channels/telegram/`, or
  `channels/discord/` — each follows the same shape (a `router.py` with
  `handle_incoming_message()` calling `core.chat.ask()`)

## Code of Conduct

Be respectful and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Questions

Open a [Discussion](../../discussions) or reach out via [ragleap.com](https://ragleap.com).
