# ragleap-app-chart

A generic, reusable Helm chart for deploying arbitrary services to
Kubernetes — built by RagLeap, but not specific to RagLeap.

Unlike `ragleap-ops` (which is hardcoded to RagLeap Core's own 4
services), this chart takes an arbitrary `services:` list in
`values.yaml` and renders resources for each service via range loops.
Point it at your own app; it doesn't know or care what RagLeap is.

## Status

Design only. See `GENERIC-K8S-CHART-PROPOSAL.md` at the repo root for
the full design rationale. No templates or live testing exist yet —
this scaffold exists so release automation can version this package
once real chart content is built.

## Design principles (from the proposal doc)

- Arbitrary service list via `range` loops — not hardcoded names
- Secure-by-default: NetworkPolicy, SecurityContext, and resource
  limits apply automatically unless explicitly overridden
- Proven against a non-RagLeap toy app before calling any feature done
  — genericity is only real once demonstrated against something that
  isn't RagLeap itself
