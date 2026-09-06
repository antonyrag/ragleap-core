# Generic Kubernetes Deployment Chart — Design Proposal

**Status: proposal, not yet built. Nothing in this document is implemented.**

## Why this is a separate effort from `ragleap-ops`

`ragleap-ops` is intentionally hardcoded to RagLeap's own stack (`db`,
`app`, `voice`, `neo4j` — real service names, real image, real env vars).
That's correct for its actual job: deploying RagLeap Core for
self-hosters. It is not, and was never meant to be, a tool a developer
with an unrelated app could use.

This proposal is for a genuinely different, reusable chart — tentatively
named `k8s-app-chart` — that any developer could point at their own
services. `ragleap-ops` is not modified by this work; it keeps working
exactly as it does today.

## What "generic" actually means (the real requirement)

Today's templates assume 4 named services with hardcoded labels
(`app: ragleap-db`) and a fixed dependency graph. A generic chart needs
to accept an arbitrary list of services and render Deployment/Service/
NetworkPolicy resources per entry, e.g.:

```yaml
services:
  - name: web
    image: myorg/myapp:latest
    port: 3000
    replicaCount: 2
    persistent: false
    env:
      - name: DATABASE_URL
        valueFrom: { secretKeyRef: { name: app-secrets, key: db-url } }
    dependsOn: [postgres]

  - name: postgres
    image: postgres:16
    port: 5432
    persistent: true
    storage: 10Gi
```

This requires real Helm `range` loops over `.Values.services`, not
hardcoded per-service template files. That's the core engineering work.

## What's reused from `ragleap-ops` (proven, not re-invented)

- Sealed Secrets workflow and README documentation pattern
- NetworkPolicy design (deny-by-default, explicit allow via labels) —
  generalized to derive `from`/`to` rules from the `dependsOn` field
- Ingress + cert-manager Certificate pattern, generalized to one
  Ingress per service that declares `expose: true`
- Multi-environment values overlay pattern (`values-{dev,staging,prod}.yaml`)
- The same live-testing discipline: every claim verified on a real
  cluster before being called done, honest documentation of what
  wasn't tested and why

## What this explicitly does NOT attempt to solve (out of scope for v1)

- StatefulSet support (only single-replica `persistent: true` PVC-backed
  services, same limitation `ragleap-ops` already has for db/neo4j)
- Multi-container pods / sidecars
- Arbitrary Ingress path-based routing (one host per service only)
- A GUI, CLI wizard, or `create-app` scaffolding tool — this is a Helm
  chart, not a platform
- Terraform / cluster provisioning (separate, later effort if pursued)

## Open questions needing a real answer before building

1. **Package location**: new top-level package (e.g.
   `packages/k8s-app-chart/`) in this same monorepo, or a fully
   separate repo? (Same tradeoff the original `ragleap-ops` handover
   doc raised and left for maintainer decision — same call applies here.)
2. **Distribution**: PyPI (matching the `ragleap-ops` precedent, even
   though this ships no Python either), or a Helm chart repository
   (the more idiomatic distribution method for a chart with no
   Python component at all)?
3. **Naming**: is `k8s-app-chart` the right name, or does this belong
   under the `ragleap-` prefix despite not being RagLeap-specific?

## Real next step

Maintainer answers the three open questions above. Only then does
scaffolding/template work begin — same discipline as every other
package in this repo: real bytes, live-tested on a real cluster,
honest documentation of what was and wasn't verified.

## Decisions — resolved 2026-09-06

The three open questions above are now answered. This section is an
addition, not a silent edit — the original open questions above are
left intact as the historical record of what was asked.

1. **Naming: `ragleap-app-chart`.** Every piece of existing package
   infrastructure (wiki live-packages table, packages.ragleap.com,
   ragleap.com/library's `PYPI_PROJECTS` stats puller, root README
   badge/install/package-list) is built around cataloging `ragleap-*`
   packages. Branding this under the RagLeap name doesn't compromise
   its generic *functionality* — the real requirement this doc cares
   about. `k8s-app-chart` remains a reasonable alternative if a
   maintainer wants to revisit this later; not a closed door.

2. **Location: same monorepo**, `packages/ragleap-app-chart/`. A
   separate repo would mean rebuilding CI, PyPI OIDC Trusted
   Publishing, and release automation from scratch for no concrete
   benefit today. Splitting out later remains possible if a distinct
   contributor community forms around this package specifically.

3. **Distribution: PyPI first.** Reuses the fully proven `release.yml`
   / OIDC workflow with zero new infrastructure risk, matching the
   same rationale already established for `ragleap-ops` ("ships no
   functional Python, just versions/publishes the chart"). A native
   Helm/OCI registry (`ghcr.io` via `helm push`) is a real, deliberate
   follow-up worth pursuing once the chart itself is proven — many
   Helm-first developers won't want a `pip install` wrapper — but it
   is not a v1 blocker. Same discipline as sequencing Observability
   before AIOps: don't build new distribution infrastructure ahead of
   proven need.

**Status update:** package scaffold (`pyproject.toml`, `src/`,
`tests/`) already created under `packages/ragleap-app-chart/`,
mirroring `ragleap-ops`'s original scaffold commit. No Helm chart
templates yet — that remains the next real piece of work, building
out the `services:` schema sketched earlier in this document.
