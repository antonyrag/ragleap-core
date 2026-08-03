# Security Policy

## Supported Versions

`ragleap-rag` is under active development. Security fixes are made against the
**latest published PyPI release only**. There is no long-term-support branch at
this stage of the project.

| Version | Supported |
|---|---|
| Latest (currently 0.11.x) | ✅ |
| Older releases | ❌ (please upgrade) |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, report it privately using one of these methods:

1. **GitHub Security Advisories (preferred):** open a private report via
   [github.com/antonyrag/ragleap-core/security/advisories/new](https://github.com/antonyrag/ragleap-core/security/advisories/new)
2. **Email:** send details to the address listed on the maintainer's GitHub
   profile ([@antonyrag](https://github.com/antonyrag)).

Please include:
- A description of the vulnerability and its potential impact
- Steps to reproduce, or a minimal proof-of-concept
- The affected version(s) of `ragleap-rag`

## What to Expect

This is a solo-maintained open-source project — there is no dedicated security
team and no formal SLA. That said, here's the realistic process:

- You'll get an acknowledgment as soon as the maintainer sees the report
  (typically within a few days).
- If confirmed, a fix will be prioritized over other roadmap work and shipped
  as a patch release, with the version noted in `CHANGELOG.md`.
- Credit is given to the reporter in the release notes, unless you'd prefer
  to stay anonymous — just say so in your report.
- Low-severity issues (e.g. requiring an already-compromised API key, or
  affecting only local/dev usage with no realistic production exposure) may
  be fixed on a slower, non-emergency timeline.

## Scope

This policy covers the `ragleap-rag` package itself (`packages/ragleap-rag/`)
and other code in this repository. It does **not** cover:

- Vulnerabilities in third-party dependencies (please report those upstream —
  though flagging them here is still welcome so they can be tracked/patched
  on our side too)
- The separate production `ragleap-backend` platform, which is a private
  repository outside this project's scope

## Known Limitations (Honest Disclosure)

In the spirit of this project's "verified claims, not marketing claims"
standard: `ragleap-rag` has not undergone a formal third-party security audit.
Guardrail hooks (`input_guardrails`/`output_guardrails`) are extension points
for user-supplied validators — the library does not itself guarantee
protection against prompt injection, PII leakage, or malicious document
content unless you configure guardrails for your use case.
