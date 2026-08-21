# GDPR / SOC 2 Readiness Notes (DRAFT — PREP WORK ONLY)

**Status: draft prep documentation. Not a compliance certification. Not
legal advice. Does not mean RagLeap is GDPR-compliant or SOC 2-certified.**

This document exists so that a future real audit (legal counsel for GDPR,
an accredited auditor for SOC 2) has an honest starting inventory instead
of starting from zero. It is explicitly **not**:

- A GDPR compliance certification (no such single certification exists —
  GDPR compliance is a legal determination, not a badge)
- A SOC 2 report (that requires an accredited third-party auditor running
  an actual audit over a defined observation period, typically 6–12
  months of evidence)
- A substitute for hiring a privacy lawyer if RagLeap ever processes EU
  personal data at scale, or a compliance firm if a customer requires a
  real SOC 2 Type II report

If a customer asks "are you GDPR compliant?" or "do you have a SOC 2
report?", the honest current answer is **no, and here's what exists
instead** — this document, plus whatever's true at the time of asking.

---

## Part A: GDPR readiness notes

### A1. What actually touches personal data today

| Component | Personal data involved? | Where it lives |
|---|---|---|
| `ragleap-rag` / `ragleap-graph` (open-source, self-hosted) | Whatever the customer chooses to ingest — entirely customer-controlled, on customer infrastructure | Customer's own Neo4j/vector DB/Postgres |
| Audit logging (`ragleap-graph` v0.6.6+) | `user_id` field, `namespace`, action metadata — opt-in, customer-supplied database | Customer's own Postgres, never RagLeap's |
| Commercial `ragleap.com` SaaS | Workspace data, potentially including end-customer PII depending on what tenants store | RagLeap-operated infrastructure — **this is the part that actually needs real GDPR review**, not the open-source libraries |

**Honest note:** the open-source packages (`ragleap-rag`, `ragleap-graph`)
are architecturally "data processor-neutral" — they don't phone home,
don't centrally store customer data, and the customer chooses what goes
into their own database. GDPR exposure for the *libraries themselves* is
low by design. GDPR exposure is concentrated entirely in the **commercial
SaaS platform**, which this document does not have visibility into in
detail — that needs its own dedicated review, likely with a lawyer, not
just an engineering write-up.

### A2. GDPR principles — honest current state, not aspirational

| Principle | Current state | Gap |
|---|---|---|
| Lawful basis for processing | Not formally documented for the SaaS platform | Needs real legal input — what's the lawful basis for each category of data the platform touches? |
| Data minimization | No formal review has been done | Needs an actual data inventory of what `ragleap.com` collects, beyond what's in this document |
| Right to erasure | Not yet implemented as a customer-facing feature on the SaaS platform (as far as this document's author knows) | Needs a real "delete my data" flow, tested, not just a database `DELETE` decided ad hoc |
| Data Processing Agreements (DPAs) | None currently exist between RagLeap and customers | Needs actual legal drafting, not something this document can produce |
| Breach notification process | No formal process documented | Needs a written incident response plan with real notification timelines (72-hour GDPR requirement) |
| International data transfer (if EU data leaves the EU) | Not assessed | Needs to know where `ragleap.com`'s infrastructure is actually hosted |

### A3. What would need to happen before claiming GDPR compliance

1. A real data inventory of the SaaS platform specifically (not the
   open-source libraries) — what's collected, why, where it's stored,
   who can access it
2. A lawyer confirming lawful basis, drafting a real DPA template, and
   confirming breach notification obligations
3. Actually implementing right-to-erasure and right-to-access as working
   features, not just policy statements
4. A documented incident response plan

**None of the above exists yet.** This document is step zero — an honest
map of what's missing, not a claim that any of it is done.

---

## Part B: SOC 2 readiness notes

### B1. What SOC 2 actually requires (for calibration)

SOC 2 is not a single checklist — it's an audit against five possible
"Trust Services Criteria" (Security, Availability, Processing Integrity,
Confidentiality, Privacy), and a real SOC 2 Type II report requires an
independent, accredited CPA firm observing controls operate correctly
over a period of months. **This cannot be self-certified, and nothing in
this repository or this document constitutes a SOC 2 report.**

### B2. Honest current-state inventory against common SOC 2 control areas

| Control area | Current state | Gap |
|---|---|---|
| Access control | VPS access is `srv1477778`, solo-maintainer administered; no formal access control policy documented | Needs a written access control policy, even for a team of one — auditors expect documentation regardless of team size |
| Change management | Real, followed-in-practice discipline exists (the 14-step release cycle, PR-based merges, CI gating via GitHub Rulesets) | This is a genuine strength — it's just not written up as a formal "change management policy" document yet |
| Monitoring / logging | `ragleap-graph`'s own audit logging exists (v0.6.6+), but this covers the library's Neo4j operations only — no platform-wide security monitoring/SIEM exists | Needs platform-level security monitoring, not just one package's audit feature |
| Vulnerability management | `ragleap-rag` has CodeQL + Dependabot configured (per the August 7 session) | This is a real, existing control — worth citing to an auditor. `ragleap-graph` should get the same treatment if it hasn't already |
| Incident response | No formal, written incident response plan exists | Needs to be written, even in draft form, before any real audit conversation |
| Vendor/subprocessor management | Not documented — what third parties does `ragleap.com` rely on (hosting provider, LLM providers, etc.)? | Needs an inventory; likely already knowable from the `.env`/config but not written up as a formal vendor list |
| Business continuity / backup | Not documented in a form an auditor would recognize | Needs a written backup/recovery policy — even if backups exist informally, auditors want documented, tested procedures |

### B3. What a real path to SOC 2 would actually require

1. Choosing which Trust Services Criteria to pursue (Security is the
   baseline; Availability/Confidentiality are common add-ons depending
   on customer demands)
2. Hiring an accredited auditing firm — this is a paid, multi-month
   engagement, not something achievable through documentation alone
3. Likely a readiness assessment first (sometimes called a "Type I" dry
   run) before a real Type II observation period
4. Realistically, this is typically pursued once there's a paying
   enterprise customer specifically requiring it as a contractual term —
   pursuing it speculatively before that demand exists is usually not
   worth the cost for an early-stage project

**Honest recommendation:** given RagLeap's current stage (solo founder,
early customer base), formal SOC 2 certification is very likely premature
to pursue proactively. The better near-term move is keeping this honest
inventory current, and only starting the real (expensive, multi-month)
process once a specific customer contract requires it.

---

## Part C: Cross-references

- Security self-review checklist: issue #176 (prep only, not a substitute
  for #10's real independent audit)
- `VERSIONING.md` (#177, draft) — relevant to SOC 2's change-management
  evidence once adopted
- SLA template (#178) — the "data handling" section there should stay in
  sync with whatever's decided here

---

*This is prep documentation only, created per issue #179. Do not
represent to any customer or on any public page that RagLeap is GDPR
compliant or SOC 2 certified based on this document. If either claim is
ever made, it must be backed by the real legal review / accredited audit
described above, not this inventory.*
