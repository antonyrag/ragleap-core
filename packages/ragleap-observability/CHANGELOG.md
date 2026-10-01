# Changelog

All notable changes to `ragleap-observability` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.0] - 2026-10-01

### Added

- Optional Slack and email AlertManager receivers, configured under `alertmanager.receivers.*` in `values.yaml`. Both are **disabled by default**, so existing installs keep the placeholder webhook and render exactly as before.
- Credentials are never stored in values or the ConfigMap. They are read from a user-created Secret (`alertmanager.receivers.secretName`, default `ragleap-alertmanager-secrets`) mounted read-only at `/etc/alertmanager-secrets`, using AlertManager's `api_url_file` (Slack) and `smtp_auth_password_file` (email).
- `required` guards on `smarthost`, `from`, `username` and `to`: enabling email with any of them missing fails at `helm template`/`helm install` with a clear message, not at runtime.

### Verified

- `helm template` across four scenarios: defaults (placeholder still renders, one receiver block), Slack only, Slack plus email, and email enabled with missing fields (fails with the expected `required` error).
- `amtool check-config` on the pinned `prom/alertmanager:v0.27.0` image accepts the fully rendered Slack-plus-email config.
- Live on a real `kind` cluster, against a Slack-compatible stand-in receiver: the Secret mounts read-only in the real pod, the rendered config is correct in-cluster, and a manually posted alert is delivered after the 30s `group_wait`.
- Real rule end to end: with `postgres-exporter` scaled to 0, `PostgresExporterDown` went none, pending, then firing after exactly 5 minutes, and a `[FIRING:1]` payload was delivered. After the exporter recovered, a `[RESOLVED]` payload was delivered about 4 minutes later (consistent with `group_interval: 5m`).
- AlertManager's Slack client requires the receiver to answer with `ok` in the response body. An empty 200 is logged as an unrecoverable error. Real Slack does this, but any stand-in must too.

### Known limitations

- No real Slack or email notification has been sent and confirmed. All delivery tests used a Slack-compatible stand-in receiver.
- PagerDuty is not supported.
- A missing Secret or Secret key leaves the AlertManager pod stuck in `ContainerCreating` (a loud failure, by design).
- The ConfigMap does not trigger a restart on change. Run `kubectl rollout restart deploy/ragleap-alertmanager` after changing receivers.
- AlertManager state (silences, notification log) is still on `emptyDir` and lost on pod restart.

## [0.3.0] - 2026-09-27

### Added

- AlertManager deployment (Deployment, Service, ConfigMap), wired end-to-end to Prometheus (`alerting:` block + `rule_files:`). No real notification receiver configured yet -- the default route points at a placeholder webhook URL that will fail every send, stated plainly in `values.yaml`. Alert routing, grouping, and silencing all work for real; delivery to a human does not, until a real Slack/email/PagerDuty receiver is configured.
- First real alerting rule: `PostgresExporterDown` (`up{job="ragleap-postgres"} == 0` for 5m), targeting an actual live, proven service in this cluster rather than a synthetic example.
- New `ragleap-prometheus-rules` ConfigMap, mounted into Prometheus alongside its existing config/data volumes.

### Fixed

- **Prometheus's Deployment had no explicit rollout strategy, defaulting to Kubernetes' standard RollingUpdate.** Its ReadWriteOnce PVC holds Prometheus's TSDB data directory, which only one process can lock at a time. The first real rollout since this Deployment was created (triggered by this AlertManager work) surfaced the conflict immediately: the new pod tried to start alongside the still-running old pod and failed with `opening storage failed: lock DB directory: resource temporarily unavailable`, crash-looping until the old pod was manually cleaned up. This was a latent bug from the original Prometheus deployment, not something this AlertManager change introduced -- it simply had never been exercised by a real rollout before. Fixed by setting `strategy: type: Recreate`, which fully terminates the old pod before starting the new one.

### Verified

- Prometheus's `/api/v1/rules` confirms the `PostgresExporterDown` rule loaded correctly (health: ok, real evaluation timestamp).
- Prometheus's `/api/v1/alertmanagers` confirms AlertManager genuinely registered as an active target (`http://ragleap-alertmanager:9093/api/v2/alerts`), zero dropped.
- AlertManager's own `/-/ready` returns OK.

### Known limitations

- No real AlertManager receiver configured -- alerts are correctly routed and grouped but not delivered to any human yet.
- AlertManager's state (silences, notification log) uses emptyDir, not a PVC -- lost on pod restart. Acceptable for a first pass; revisit if silences need to survive restarts.
- **No canary or blue-green deployment strategy exists anywhere in this project.** Every Kubernetes Deployment uses either the Kubernetes default RollingUpdate (implicit, not deliberately built) or, as of this release, an explicit Recreate strategy for Prometheus specifically (necessary due to its single-writer TSDB storage, not a general pattern). Canary/blue-green would need a dedicated tool (Argo Rollouts, Flagger) or service-mesh/Ingress traffic-splitting, both of which depend on GitOps tooling (step 14 of the master plan, ArgoCD/Flux) that has not been started. This is not an oversight -- it is the natural consequence of GitOps being correctly sequenced later, not a gap in this specific release.
- SLO/SLI dashboards remain unbuilt -- correctly sequenced after alerting exists, per the project's own build order.

## [0.2.1] - 2026-09-25

### Fixed

- README "Status" and "Planned build order" sections were stale on the v0.2.0 PyPI release -- still said Grafana/Loki were not yet built, despite both being live-verified and shipped in that same release. Corrected to match the CHANGELOG's actual v0.2.0 content.

## [0.2.0] - 2026-09-25

### Added

- Prometheus server and Grafana, live-verified end-to-end on a real kind cluster. `values.yaml` already anticipated this config (image, retention, scrapeInterval) but the actual Prometheus Deployment/Service/PVC templates never existed -- only the exporter and a scrape ConfigMap with nothing consuming it. Added, plus Grafana (Deployment, Service, Secret for admin credentials with a placeholder value and a clear REPLACE comment, and a datasource ConfigMap pointing at the new Prometheus service).
- Loki deployment (Deployment, ConfigMap, filesystem-backed storage) and Promtail DaemonSet for log shipping, both live-verified end-to-end: 21+ real log streams confirmed in Loki with correct `namespace`/`pod`/`container` labels, spanning nearly every pod in the cluster.
- Grafana datasource ConfigMap now conditionally wires in Loki (`{{- if .Values.loki.enabled }}`) alongside the existing Prometheus datasource.
- `values.yaml`: new `loki:` and `promtail:` blocks (image, port, retention, enabled flags).
- Real UIDs confirmed via `docker run` before use, not assumed: `prom/prometheus:v2.55.1` -> uid=65534(nobody), `grafana/grafana:11.3.1` -> uid=472(grafana).
- Deliberately did NOT enable `readOnlyRootFilesystem` on Prometheus or Grafana -- per this session's own neo4j finding, blindly enabling this flag without investigating what each image's entrypoint writes on startup is a real, non-obvious risk. Needs its own dedicated investigation before enabling.

### Fixed

- `postgres-exporter` had `runAsNonRoot: true` with no `runAsUser` set. The image's Dockerfile sets its user by name (`nobody`) rather than a numeric UID, which Kubernetes cannot verify against `runAsNonRoot` without an explicit numeric value -- failed on real cluster with `container has runAsNonRoot and image has non-numeric user (nobody), cannot verify user is non-root`. Fixed with `runAsUser: 65534`, confirmed via `docker run --rm --entrypoint id`.
- Cross-namespace DNS lookup failure in Promtail's Loki client. The client URL used a bare service name (`ragleap-loki`), which only resolves via CoreDNS's `kubernetes` plugin within the querying pod's own namespace. Since Promtail runs in `ragleap-observability-agents` and Loki runs in `ragleap-core`, every push failed with `dial tcp: lookup ragleap-loki ... server misbehaving`. Symptom looked exactly like a CoreDNS health problem but a full CoreDNS restart did not fix it. Fixed by switching to `ragleap-loki.{{ .Release.Namespace }}.svc.cluster.local`.
- `kubernetes_sd_configs` produced 0 active targets despite correct discovery. Root-caused through several layers: (1) Promtail auto-injects a node-scoping field selector built from `$HOSTNAME`, which without an explicit override defaults to the pod's own name rather than the real node name -- fixed by setting `HOSTNAME` via the Downward API. (2) A hand-built multi-capture-group regex for `__path__` matched real on-disk paths exactly by hand, yet Promtail's own `/ready` endpoint still reported "unable to find any logs to tail" -- replaced with Grafana's own canonical production pattern (`__meta_kubernetes_pod_uid` + `__meta_kubernetes_pod_container_name` joined by a literal `/` separator, default single-capture regex, wrapped in `/var/log/pods/*$1/*.log`). Also added the `cri: {}` pipeline stage needed to correctly parse Kubernetes' CRI log line format.
- A missing newline silently corrupted the ConfigMap's YAML document boundary, merging the ConfigMap and the next resource together -- caused a silent `helm upgrade` "success" that never actually created the ConfigMap, an "unknown field \"data\"" warning, and a downstream Promtail crash-loop.
- Loki's default ingestion rate limit (4 MB/s) was too low for the burst of historical log replay generated every time Promtail's `positions.yaml` reset. Fixed by raising `ingestion_rate_mb: 16` / `ingestion_burst_size_mb: 32`.
- Removed the temporary `static-pod-logs` diagnostic scrape job -- it silently starved the real `kubernetes-pods` job of every file it touched since `positions.yaml` keys purely by file path, not by job.

### Verified

- Full pipeline confirmed live, layer by layer: Prometheus's `/api/v1/targets` confirmed target health; Grafana's `/api/health` and `/api/datasources` confirmed; `pg_up` queried through Grafana's own datasource proxy.
- Loki ingestion proven end-to-end via `/loki/api/v1/series`: 21 real series returned across 5 namespaces, each with correct labels.
- Promtail's own `/ready` endpoint returns `Ready`.

### Known limitations

- Neo4j Prometheus support genuinely unverified. `neo4jExporter` stays disabled until independently live-verified.
- AlertManager, SLO/SLI dashboards, and a recurring log-shipping health check remain unbuilt.
- Loki's retention (`168h` / 7 days) is unverified for real storage-sizing needs.
