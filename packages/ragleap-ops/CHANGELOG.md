# Changelog

All notable changes to `ragleap-ops` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-08-30

### Added

- Initial release: Kubernetes Deployment + Service manifests for all four `docker-compose.yml` services (`db`, `app`, `voice`, `neo4j`), translated field-by-field from the real compose file rather than assumed.
- Live-tested end-to-end on a local `kind` cluster: all four pods reached `1/1 Running` with zero restarts. A `db` liveness-probe timing bug was found live (the original `initialDelaySeconds: 10` was too short for first-boot image pull + PVC attach, causing kubelet to kill a still-starting container) and fixed (`initialDelaySeconds: 45`, `failureThreshold: 6`), then re-verified clean.
- `app`/`voice` pull a real image (`ghcr.io/antonyrag/ragleap-app:latest`, built from the existing repo-root `Dockerfile` and pushed to GHCR) via a `ghcr-pull-secret` `imagePullSecret`.
- Python package scaffold (`pyproject.toml`, `src/ragleap_ops/`) added purely so this content can be versioned and released via the existing `release.yml` automation — the package itself ships no functional Python code, only the `k8s/` manifests.

### Known limitations

- No Helm chart yet — raw manifests were proven first via live cluster testing; Helm wrapping is planned next.
- `app-env-secret.yaml` and the real contents of `db-schema-configmap.yaml`'s referenced `schema.sql` are environment-specific and intentionally not shipped in this package — see README for how to regenerate them locally via `kubectl create secret`/`kubectl create configmap`.
- PVC storage sizes (`5Gi`) are placeholder defaults, not derived from any real capacity planning — `docker-compose.yml`'s named volumes are unbounded, so there was no real size to translate from.

## [0.2.0] - 2026-08-31

### Added

- Helm chart (`helm/ragleap-ops/`) wrapping all four `k8s/` manifests (db, app, voice, neo4j) with real configurable `values.yaml` — image tags, resource limits, storage sizes, probe timings, credentials.
- Real database schema (`db/schema.sql`) is packaged into the chart via Helm's `.Files.Get`, copied verbatim from the repo's real schema file, not reproduced from memory.

### Fixed

- `neo4j`'s liveness probe had no explicit `failureThreshold` in the Helm template (unlike the raw k8s manifest, which was already correctly set) — defaulted to Kubernetes' built-in `3`, too tight for JVM startup under CPU contention. Found via live `helm install`/`helm upgrade` testing on a real `kind` cluster (not caught by `helm lint` or `helm template`, since those don't exercise runtime behavior). Fixed to match the readiness probe's more generous timing (`initialDelaySeconds: 60`, `failureThreshold: 6`).

### Verified

- All four services (`db`, `app`, `voice`, `neo4j`) independently reached `1/1 Running` with zero restarts for extended periods (60+ minutes) on a real `kind` cluster via `helm install`.
- Added explicit `resources.requests`/`limits` for `neo4j` (512Mi memory request, 1Gi limit; CPU tuned to 50m during testing) after live testing on this session's VPS surfaced real host-level CPU/memory contention (the test VPS runs several other production services concurrently) — this is a permanent, worthwhile chart improvement, not a workaround specific to this host.

### Known limitations

- Full 4-service stack was demonstrated stable in bounded windows (60+ min) on a resource-constrained single-node test host that was also running unrelated production services. Extended (multi-hour) concurrent-stack stability was not verified on this specific host due to genuine host-level memory/CPU exhaustion (swap fully exhausted at points during testing) — not a chart defect, but an honest scope boundary on what was tested. A dedicated cluster (not sharing a host with other production workloads) is expected to have materially more headroom.
- CPU resource values (`cpu: 50m` for neo4j) were tuned against a heavily constrained single-vCPU-allocatable test node and should be reviewed against real target-cluster capacity before production use, not assumed as a universal recommendation.
- Same limitations as v0.1.0 still apply: `app-env-secret.yaml`/`db-schema-configmap.yaml`'s real content are environment-specific and not shipped; PVC storage sizes remain placeholder defaults.
