# Changelog

All notable changes to `ragleap-app-chart` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Generic `services:` schema in `values.yaml` — arbitrary list of services, each rendering its own Deployment, Service, and (conditionally) PVC, NetworkPolicy, and Ingress via Helm `range` loops. Not hardcoded to any specific app.
- Deny-by-default NetworkPolicy per service, with ingress rules derived automatically from other services' `dependsOn` entries — same design philosophy as `ragleap-ops`'s NetworkPolicies, generalized to arbitrary service names.
- Per-service `resources` and `securityContext` overrides, falling back to chart-level `defaultResources`/`defaultSecurityContext` when omitted — secure-by-default per the design proposal's stated principles.
- Optional per-service Ingress + cert-manager TLS via `expose: true` + `hostname`.

### Verified

- `helm lint` passes clean against the base `values.yaml` example (two services: stateless+exposed `web`, stateful+internal `postgres`).
- `helm template` output confirmed correct for: per-service resource/securityContext override vs. chart-default fallback, persistent-vs-non-persistent volume mounting, `dependsOn`-derived NetworkPolicy ingress rules (verified both the deny-all case and the allow-from case), and `expose`-gated Ingress generation (exactly one Ingress rendered, for the exposed service only).

### Known limitations

- **No live cluster deploy performed yet.** All verification above is template-rendering level (`helm lint`/`helm template`) only — held back due to sustained high CPU steal time on the test VPS during this session. Live `kind` cluster testing (pods actually reaching `Running`, NetworkPolicy enforcement actually tested under Calico, Ingress+TLS chain actually proven) remains outstanding before this chart can be called genuinely proven, matching the standard every other feature in this repo has been held to.
- No CI-based chart testing (`ct`/`helm unittest`) yet — verification so far is manual, not automated.
- StatefulSet support, multi-container pods, and path-based Ingress routing are explicitly out of scope for v1, per `GENERIC-K8S-CHART-PROPOSAL.md`.
