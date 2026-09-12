# Changelog

All notable changes to `ragleap-app-chart` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `command`/`args` support per service in `deployment.yaml` -- a real, structural gap found while building the worked example below (not previously supported at all, for any reason, on any service). Discovered live: a worked example using `hashicorp/http-echo` set its message via `env:`, deployed successfully, but returned the image's baked-in default text instead -- because `http-echo` is configured via a command-line flag (`-text=...`), not an environment variable, and the chart had no way to override the container's command/args at all. Fixed by mirroring the exact pattern already used in `ragleap-ops` (`command: {{ .Values.voice.command | toJson }}`). Re-deployed live against the same real kind cluster after the fix and confirmed the correct response (`hello from ragleap-app-chart`) via a live port-forward and curl -- not just `helm template` output.
- Worked example (`values-example.yaml`, `EXAMPLE.md`) -- a genuinely different, non-RagLeap stack (`redis` + a small HTTP service) deployed live end-to-end on a real kind cluster. Chosen specifically to prove a different case than the existing default `web`+`postgres` example: Redis's official image already defaults its data directory to `/data`, so this proves a persistent service that needs zero mount-path overrides, in contrast to postgres needing an explicit `PGDATA` override. See EXAMPLE.md for the full walkthrough.

### Added (prior)

- Multi-environment values pattern (`values-dev.yaml`, `values-staging.yaml`, `values-prod.yaml`), porting the proven approach from `ragleap-ops` into this generic chart. Because this chart's `services:` field is a list (not a scalar), and Helm does not merge list entries by key, each environment file is a full override, not a partial one -- a genuine structural difference from `ragleap-ops`'s scalar-field overrides, documented inline in each file. Verified via `helm lint` (clean) and `helm template -f values-{env}.yaml` for all three environments: dev renders 1 replica + ingress disabled, staging renders 1 replica + ingress enabled with a staging hostname, prod renders 3 replicas for the stateless example service and correctly keeps the stateful example service at 1 replica, matching the same stateful-service-does-not-scale-via-replicaCount principle already established in `ragleap-ops`.

### Fixed

- First live cluster deploy (helm install against a real kind cluster) found 2 real bugs in the default example config, neither previously caught by helm lint/helm template alone:
  1. `defaultSecurityContext`'s `runAsNonRoot: true` had no accompanying `runAsUser` -- rejected postgres:16 outright, same class of bug found and fixed in ragleap-ops earlier the same day (confirmed via `docker run --rm postgres:16 id postgres` -- UID 999, not assumed). Fixed generically: added an opt-in per-service `initChown` flag in deployment.yaml that renders a one-time root `fix-permissions` init container using the service's own declared `securityContext.runAsUser` -- not hardcoded to any specific UID, since this chart is not RagLeap-specific and different services will need different UIDs.
  2. The chart hardcodes `/data` as the mount path for any `persistent: true` service. postgres's official image defaults to `/var/lib/postgresql/data`, not `/data` -- without an explicit `PGDATA` override, postgres would have initialized on the container's ephemeral filesystem, silently NOT persisting to the actual PVC. This is a real, generic risk for any persistent service whose image doesn't default to `/data` specifically -- documented here as a known gap; the chart does not currently warn or validate this automatically.

### Verified

- Full `helm install` against a real local kind cluster (Docker Desktop, Windows) using the chart's own default example `services:` list (web + postgres) -- the genericity proof the design proposal explicitly requires ("proven against a non-RagLeap toy app"). After the above fixes: `postgres` reached `1/1 Running`, 0 restarts sustained. Verified data genuinely persists to the mounted volume, not just that the pod is green: `SHOW data_directory;` confirmed `/data/pgdata`, matching the PGDATA override, not the container's ephemeral root filesystem.
- `web`'s `ImagePullBackOff` is expected (default example uses a placeholder `myorg/myapp:latest` image that doesn't exist on any registry) and doesn't reflect on chart correctness.
- Confirmed the existing NetworkPolicy/PVC/resources/securityContext override logic (previously only template-verified via helm template) now also proven against real deployed resources, not just rendered YAML.

### Known limitations

- The hardcoded `/data` mount path (see Fixed #2 above) is a real generic risk, not just a postgres-specific quirk -- any persistent service whose image doesn't default its data directory to `/data` needs an explicit env override (or a future chart enhancement to make the mount path itself configurable per-service, not yet built).
- `initChown` requires the service to also declare its own `securityContext.runAsUser` -- if a service sets `initChown: true` without `runAsUser`, the rendered chown command would be malformed (empty UID). Not currently validated by the chart; a real user mistake here would fail at apply-time, not before.


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
