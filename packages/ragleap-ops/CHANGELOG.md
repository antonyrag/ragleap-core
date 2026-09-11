# Changelog

All notable changes to `ragleap-ops` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- `readOnlyRootFilesystem` enabled across `db`, `app`, `voice` (both raw `k8s/` manifests and Helm chart templates) -- the previously-flagged gap ("intentionally NOT enabled yet -- not live-tested") is now closed for these three services. `neo4j` received the same writable-path mounts but the flag itself was deliberately left disabled -- the Neo4j Docker entrypoint rewrites `/var/lib/neo4j/conf` on every startup, and this has not been verified to tolerate a read-only root; documented inline in both manifest paths pending further investigation.
- Helm `app-deployment.yaml` and `voice-deployment.yaml` templates were found to have NO `securityContext` at all on either the `wait-for-db` init container or the main container -- a real, previously-undocumented gap distinct from the raw manifests (which did have SecurityContext). Closed as part of this change; both Helm templates now match the raw manifests' security posture.
- Real bug found via live testing, same class as the earlier SecurityContext finding: `app`/`voice`'s `wait-for-db` init container (`postgres:16-alpine`) had `runAsNonRoot: true` with no `runAsUser` set, in both the raw manifests (pre-existing, just never live-tested before) and the newly-added Helm securityContext blocks. Failed on real cluster with `container has runAsNonRoot and image will run as root`. Fixed with `runAsUser: 70`, confirmed via `docker run --rm postgres:16-alpine id postgres` (uid=70(postgres)), not assumed.

### Verified

- `db`: full `readOnlyRootFilesystem` live-tested on a real local kind cluster (Docker Desktop on Windows). Pod reached `1/1 Running`, 0 restarts. Unix socket created successfully at `/var/run/postgresql/.s.PGSQL.5432` (confirmed via `ls -la`, correct `postgres:postgres` ownership). `pg_isready -U ragleap` returned `accepting connections`. Schema DDL from `ragleap-db-schema` configmap applied successfully on startup.
- `neo4j`: writable-mount fix (partial, flag left off) live-tested on the same cluster. Pod reached `1/1 Running`, 0 restarts. Neo4j 5.26.30 started cleanly, Bolt (7687) and HTTP (7474) both enabled. `/logs` mount confirmed genuinely in use (`debug.log`, `neo4j.log` actively written, correct `neo4j:neo4j` ownership). `/var/lib/neo4j/run` confirmed in use (`neo4j.pid` present). Real Cypher query executed successfully via `cypher-shell` (`RETURN 1 AS test` -> `1`), confirming the database engine is genuinely functional, not just container-running.
- `app`/`voice` init containers: after the `runAsUser: 70` fix, both pods progressed cleanly past `wait-for-db` (previously `Init:CreateContainerConfigError`) with no further init-container errors.

### Known limitations

- `app`/`voice` main containers' `readOnlyRootFilesystem`/`/tmp` mount behavior could NOT be verified in this pass -- both pods reached `ImagePullBackOff` on `ghcr.io/antonyrag/ragleap-app:latest`, a private image requiring a real `ghcr-pull-secret` not available in this test session. This remains a genuinely open item, not assumed to work. Revisit once GHCR credentials are available.
- Neo4j's `/var/lib/neo4j/conf` read-only-root compatibility remains unverified -- flag intentionally left disabled, needs either entrypoint script investigation or a live attempt-and-observe test.


### Verified

- Full neo4j backup/DR restore drill performed end-to-end on a real local kind cluster -- the previously-flagged gap ("dump side verified, restore side never tested") is now closed. Real marker node created via cypher-shell, neo4j scaled to zero, `neo4j-admin database dump` taken against the unlocked PVC (36 files, 257.9MiB, matching the original session's dump size almost exactly), then `neo4j-admin database load --overwrite-destination=true` performed against the same volume, neo4j scaled back up, and the exact same marker node (same properties, same millisecond-precision timestamp) confirmed recovered via cypher-shell. Restore command completed with zero errors, notably cleaner than the noisy-but-successful Postgres restore (which produced expected `already exists` errors when restoring into a non-empty schema).


### Fixed

- Helm chart templates (`helm/ragleap-ops/templates/db-deployment.yaml`, `neo4j-deployment.yaml`) had NOT received the SecurityContext fixes from the prior raw-manifest fix (runAsUser, fix-permissions init container) -- confirmed real drift between the two deployment paths, same class of bug as the earlier neo4j probe-drift finding. Ported the identical fix to both Helm templates.

### Verified

- `helm lint` clean; `helm template` output confirmed both `fix-permissions` init containers and both `runAsUser` values (999, 7474) render correctly, not left as unresolved template syntax.
- Full `helm install` performed on a real local kind cluster (Docker Desktop on Windows). `neo4j` reached `1/1 Running` with 0 restarts. `db`'s `fix-permissions` init container completed successfully (exit code 0) and the main container reached `Ready: True`, confirming the ported fix works identically to the raw-manifest version already verified.

### Known limitations

- During this full-stack `helm install` (all 4 services deploying simultaneously, unlike the earlier minimal single-service raw-manifest test), `db` restarted twice due to `pg_isready` probe timeouts (`command timed out after 1s`/`5s`) -- root cause was real resource contention on the test laptop under the heavier simultaneous 4-service load (image pulls that normally take seconds took 50+ seconds), not a defect in the SecurityContext/init-container fix itself. The pod self-healed and reached a stable `1/1 Running` state. Worth revisiting probe timeout tuning if this recurs under realistic production load, but not treated as a blocking bug here since it reflects test-environment contention, not the fix being verified.
- `app`/`voice` could not be tested in this pass -- `ImagePullBackOff` due to missing `ghcr-pull-secret` and private image access in this fresh test cluster, expected and unrelated to this fix.


### Fixed

- SecurityContext hardening (added in a prior commit) broke real startup for `db` and `neo4j` on live cluster testing -- caught only now via an actual kind deploy, not template validation. Three real, layered issues found and fixed:
  1. `runAsNonRoot: true` alone rejected both images outright (`pgvector/pgvector:pg16` and `neo4j:5-community` both default to a root user before their entrypoints drop privileges internally) -- fixed by adding explicit `runAsUser` set to each image's real non-root UID (999 for postgres, 7474 for neo4j, confirmed via `docker run --rm <image> id <user>`, not assumed).
  2. Even with the correct UID, `initdb`/neo4j startup failed with `chmod: Operation not permitted` against the PVC-backed data directory, which K8s creates owned by root by default.
  3. Pod-level `fsGroup` alone did not resolve this -- it sets group ownership, not directory owner, and `chmod` on the directory itself requires ownership. Fixed with a dedicated `fix-permissions` init container (root, `chown -R <uid>:<uid> <mount>`, busybox:1.36) that runs once before the main container starts as its restricted UID.

### Verified

- Full backup/DR restore drill performed end-to-end on a real local kind cluster (Docker Desktop on Windows, not the constrained VPS used earlier -- VPS steal time made even minimal cluster boot fail outright, confirmed via a separate failed kubeadm init attempt). Real marker row inserted, `pg_dump` taken and byte-verified to contain it, table dropped with CASCADE, `SELECT` confirmed genuine data loss, restore performed from the dump file, `SELECT` confirmed the exact same row (same UUID, same microsecond timestamp) recovered. RTO for this single-table drill: under 2 minutes.
- `db` and `neo4j` deployments confirmed to actually reach `1/1 Running` with the fixed SecurityContext + fix-permissions init container pattern, `RESTARTS: 0` sustained.

### Known limitations

- Restoring a full-schema `pg_dump` into an already-initialized (non-empty schema) database produces expected `already exists`/`multiple primary keys` errors for every CREATE statement -- harmless (the actual data COPY statements still succeed), but noisy. A genuinely clean restore drill should target a freshly-provisioned empty database, not layer onto an existing schema the way this test did. Real operational finding, not previously documented.
- This restore drill covered Postgres only. The neo4j scale-to-zero + `neo4j-admin dump`/`load` restore path (built earlier this session) has NOT yet been live-restore-tested -- only the dump side was previously verified. Real remaining gap.
- Both fixes (runAsUser, fix-permissions init container) were verified in this session but not yet reflected in the Helm chart's equivalent templates (`helm/ragleap-ops/templates/`) -- only the raw `k8s/` manifests were fixed and tested here. The Helm chart needs the same fix, tracked as a follow-up (same class of bug as the earlier neo4j probe-drift finding between raw manifests and Helm templates).


## [0.3.0] - 2026-09-06

### Added

- Backup/DR: `backup-pvc.yaml`, `db-backup-cronjob.yaml` (daily `pg_dump`, no downtime), `neo4j-backup-cronjob.yaml` (scale-to-zero + `neo4j-admin dump`, since Community Edition has no online backup command).

### Verified

- `pg_dump` live-tested against a real running database, produced a valid dump.
- neo4j scale-to-zero + dump pattern live-tested end-to-end via a real Job, produced a genuine 257.8MiB/36-file dump successfully.
- CronJob wrapper (RBAC, scheduling) validated structurally, not exercised via an actual cron trigger this session.

### Known limitations

- Neo4j backup is fail-loud by design: a failed dump leaves neo4j scaled to 0 rather than auto-restoring, to avoid a silently-failing backup going unnoticed. Requires monitoring CronJob/Job status separately.

### Fixed

- `k8s/neo4j-deployment.yaml`'s liveness probe still had the original, pre-fix timing (`initialDelaySeconds: 20`, no explicit `failureThreshold`) even though the equivalent bug was already found and fixed in the Helm chart's neo4j template earlier this session. The two deployment paths had silently diverged. Found while live-testing backup/DR tooling on a fresh cluster -- neo4j genuinely crash-looped (kubelet killing it ~7 seconds into JVM startup, well before the database could bind its HTTP listener). Fixed to match the Helm chart's already-proven values (`initialDelaySeconds: 60`, `failureThreshold: 6`), then re-verified stable (0 further restarts after the one within the expected startup window).

### Added

- Environment overlay files (`values-dev.yaml`, `values-staging.yaml`, `values-prod.yaml`) for the Helm chart, layered on top of the base `values.yaml`.
- `app.replicaCount`/`voice.replicaCount` parameterized (were previously hardcoded to `1` in the templates, which would have silently made environment-based replica scaling impossible). `db`/`neo4j` intentionally remain hardcoded at 1 replica -- both are stateful, single-writer services on `ReadWriteOnce` PVCs.

### Verified

- Rendered output confirmed to differ correctly across all three overlays via `helm template -f values-<env>.yaml`: dev (1/1 replicas, ingress disabled), staging (1/1 replicas, ingress enabled with its own hostname), prod (3/2 replicas, ingress enabled with its own hostname).

### Added

- Optional Helm chart Ingress + cert-manager Certificate (`ingress.enabled`, default `false`) for exposing the app outside the cluster over TLS.

### Verified

- Full Ingress + TLS chain live-tested end-to-end on a real kind cluster with a genuine NGINX Ingress Controller and cert-manager, using a self-signed ClusterIssuer. Confirmed via openssl that the correct certificate (matching SNI hostname) was served, not a generic fallback. HTTP routing through the Ingress to the backend independently confirmed.

### Known limitations

- Production Let's Encrypt issuance was not live-tested this session — real ACME HTTP-01 challenges require public DNS and an internet-reachable port 80, which a local kind cluster cannot satisfy. The provided ClusterIssuer example is the standard, documented cert-manager pattern, not independently verified against a real domain.

### Added

- NetworkPolicy resources (both `k8s/` and `helm/ragleap-ops/`) restricting `ragleap-db` ingress to `ragleap-app`/`ragleap-voice` only, and `ragleap-neo4j` ingress to `ragleap-app` only (`ragleap-voice` doesn't use neo4j in the current codebase, confirmed by checking real source, not assumed).

### Verified

- NetworkPolicy enforcement mechanism live-tested end-to-end on a real kind + Calico cluster: unlabeled traffic genuinely blocked (timeout, exit code 1), correctly-labeled traffic genuinely allowed (exit code 0) — not just applied without error.
- Real label selectors cross-checked against actual Deployment manifests — confirmed exact match.

### Known limitations

- kind's default CNI does not enforce NetworkPolicy at all; testing requires Calico or another NetworkPolicy-capable CNI (documented in README).
- Full ragleap stack (db+app+voice+neo4j) was not live-tested together under Calico in this session due to genuine VPS memory constraints — Calico's own baseline overhead left insufficient headroom for reliable 4-service testing on this specific host. Enforcement mechanism and label correctness were verified separately, not as one combined integration test.


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
