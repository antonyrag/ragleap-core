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
