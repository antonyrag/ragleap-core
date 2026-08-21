# RagLeap Open-Source Support & SLA Template (DRAFT)

**Status: draft template, not adopted. Not a legal document. Not currently
in force.**

This document is a starting point for a real support/SLA policy, written
so the maintainer (or, eventually, a paying customer's legal team) has
something concrete to react to rather than a blank page. It is explicitly
**not** a substitute for:

- Actual legal review by a qualified attorney before any version of this
  is offered as a binding commitment to a paying customer
- A real support contract, which needs negotiated terms specific to each
  customer's risk tolerance and use case
- Insurance/liability review, which is out of scope for this document
  entirely

If this is ever adopted, replace this header with a real effective date
and remove the "DRAFT" framing everywhere it appears below.

---

## 1. Scope

This template applies to:
- `ragleap-rag` (PyPI, open-source, MIT-licensed)
- `ragleap-graph` (PyPI, open-source, MIT-licensed)

It does **not** apply to:
- The commercial `ragleap.com` multi-tenant SaaS platform (has, or should
  have, its own separate, dedicated SLA — this template is written for
  the open-source libraries only)
- The self-hosted edition installer/admin panel (arguably needs its own
  version of this document, since self-hosted customers have different
  failure modes — e.g. "the installer failed on their infrastructure" vs.
  "a bug shipped in a PyPI release")

## 2. Support tiers (proposed — needs a real business decision)

| Tier | Who | What's included | Open questions |
|---|---|---|---|
| Community | Anyone using the open-source packages for free | Best-effort response on GitHub Issues; no guaranteed response time | Is this even worth formalizing, or just "the current default"? |
| Paid support (not yet built) | Customers paying for a support contract | Guaranteed response time (needs a real number — see §3), direct channel (email? Slack Connect? not yet decided) | Does this exist as a product yet? If not, this whole tier is aspirational |

**Honest gap:** there is currently no paid support product. This template
assumes one might exist someday; if it doesn't, most of §3–§5 below is
premature and should be trimmed to just the Community tier.

## 3. Response time commitments (placeholders — do not treat as real numbers)

| Severity | Definition | Target first response | Target resolution |
|---|---|---|---|
| Critical | Data loss, security vulnerability, complete inability to use the package in production | `[X hours]` — not yet decided | `[X hours/days]` — not yet decided |
| High | Major feature broken, no workaround | `[X business days]` — not yet decided | `[X business days]` — not yet decided |
| Medium | Minor feature broken, workaround exists | `[X business days]` — not yet decided | Best-effort |
| Low | Cosmetic, documentation, feature request | No commitment | Best-effort |

**These numbers are placeholders.** Real numbers require deciding:
- Is this a solo-maintainer commitment (Joseph personally) or does it
  assume a support team that doesn't exist yet?
- What happens if a critical issue lands during a non-working period?
  Realistic answer for a solo maintainer: probably nothing formal yet.

## 4. What's explicitly NOT covered

- Bugs in dependencies (Neo4j, PostgreSQL, LiteLLM, provider APIs) outside
  RagLeap's own code
- Performance issues caused by the customer's own infrastructure sizing
- Custom code the customer wrote against the public API
- Anything in packages/features explicitly marked "vision" or "not yet
  scoped" in the roadmap (e.g. `ragleap-intelligence`)
- Security vulnerabilities in versions the customer hasn't upgraded to,
  once a fix has been published (see `VERSIONING.md` deprecation policy,
  once adopted)

## 5. Availability / uptime commitments

**Not applicable to the open-source packages themselves** — they run on
the customer's own infrastructure, so "uptime" is the customer's
responsibility, not something RagLeap can commit to for self-hosted
usage. If this SLA is ever extended to cover the commercial SaaS
(`ragleap.com`), that needs an entirely separate uptime/availability
section with real historical numbers, not present in this template.

## 6. Data handling & audit logging

Per the current design of `ragleap-graph`'s audit logging (v0.6.6+):
audit logs are opt-in, stored in a customer-supplied Postgres database,
not centrally by RagLeap. This template makes no data-retention or
data-processing commitments on RagLeap's behalf, because RagLeap does
not currently hold customer data centrally for the open-source packages.
If that changes, this section needs a full rewrite alongside real privacy
counsel input.

## 7. Escalation path (placeholder)

`[Not yet defined. For a solo maintainer, this is probably: GitHub Issue
→ direct email → ??? There is no formal escalation tier above that yet.]`

## 8. Real next steps before this could be offered to a paying customer

- [ ] Decide whether a paid support tier is even a near-term business
      goal, or whether this document should stay purely aspirational
- [ ] Get real legal review on every commitment before offering this to
      anyone as binding
- [ ] Decide realistic response-time numbers based on actual maintainer
      capacity, not aspirational ones
- [ ] Decide whether self-hosted and SaaS need separate SLA documents
      (likely yes, given very different failure modes)
- [ ] Cross-reference with `VERSIONING.md` (draft, #177) — the SLA's
      "which versions are supported" section should match whatever
      deprecation policy is eventually adopted there

---

*This is a working draft, created as prep work per issue #178. It should
not be linked from any customer-facing page or repository README until
it has real legal review and the placeholders above are filled with
actual decisions, not placeholders.*
