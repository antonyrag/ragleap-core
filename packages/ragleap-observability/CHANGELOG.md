# Changelog

All notable changes to `ragleap-observability` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.6.2] - 2026-10-08

### Changed

- **postgres-exporter upgraded from `v0.15.0` to `v0.20.1`.** The Trivy scan on v0.15.0 reported 48 HIGH/CRITICAL findings with a fix available; the scan of the new image has not been read yet (the first run of the scheduled Trivy workflow will report it).

### Upstream changes worth knowing

None of these affect this chart's defaults, because the exporter container is started with no custom `args` and no dashboards or alert rules in this chart use the renamed metrics. They matter if you add your own flags, dashboards or log queries.

- v0.16.0: logging moved to Go `slog`. Messages and levels are the same, but fields are renamed (`ts` is now `time`, `caller` is now `source`, levels are upper-case).
- v0.20.0: the `replication_slot` collector is now `replication_slots` (flags `--collector.replication_slots` and `--no-collector.replication_slots`).
- v0.20.0: `--disable-settings-metrics` and `PG_EXPORTER_DISABLE_SETTINGS_METRICS` are removed; use `--no-collector.settings`.
- v0.20.0: `pg_replication_slot_*` metrics are renamed `pg_replication_slots_*`.

### Verified (live on kind)

- With only the exporter image changed (`kubectl set image`), against PostgreSQL 16.15: one pod Running on `v0.20.1`, 0 restarts, `postgres_exporter_build_info` reports `version="0.20.1"`, `pg_up 1`, `pg_exporter_last_scrape_error 0`.
- `DATA_SOURCE_NAME` from the existing Secret is still honoured by v0.20.1.
- Prometheus reports `up{job="ragleap-postgres"} 1` and `PostgresExporterDown` is not pending or firing.
- The container still runs as UID 65534, matching the chart's `securityContext`.

### Known limitations

- Tested by swapping the image on a running release, not by a full `helm upgrade` of this chart version.
- Tested on one PostgreSQL version (16.15) and one database. Release notes for v0.18.x and v0.19.x were not reviewed.
- Promtail `3.3.0` is still shipped. Grafana documents Promtail as end of life since March 2, 2026, so bumping it is not worthwhile; a migration to Grafana Alloy is planned instead.

## [0.6.1] - 2026-10-06

### Fixed

- **Loki retention was configured but never enforced.** `limits_config.retention_period` was set, but the `compactor` block had no `retention_enabled: true` and no `delete_request_store`, so old data was never deleted. Confirmed from Loki's own `/config` endpoint, then fixed; the new config is valid on Loki 3.6.17 and the live pod reports `retention_enabled: true`. Actual deletion of old chunks has not been observed, because test data is younger than 7 days.
- **Disabling postgres-exporter produced a permanent false alert.** The `ragleap-postgres` scrape job and the `PostgresExporterDown` rule were not gated on `postgresExporter.enabled`. Both are now gated; with the exporter off, Prometheus has no targets and no alerts (checked on a live cluster), and promtool accepts the empty config.
- **Config changes did not roll pods.** A ConfigMap change left the old pod running its old config; this hid the Loki retention fix and caught AlertManager earlier. Loki, AlertManager, Prometheus and Grafana now carry checksum annotations. Verified live: `--set loki.retention=72h` rolled the Loki pod with no manual restart.

### Upgrade note

- The first upgrade to 0.6.1 adds the annotations, so Loki, AlertManager, Prometheus and Grafana each restart once.
- Loki and AlertManager hash their values, so a change to template text alone does not roll them.

## [0.6.0] - 2026-10-03

### Changed

- Upgraded four pinned images to clear known HIGH/CRITICAL vulnerabilities. Counts are Trivy findings with a fix available, scanned 2026-10-03 (`--ignore-unfixed`, so they are not a clean bill of health):
  - AlertManager `v0.27.0` -> `v0.34.1` (96 -> 2)
  - Loki `3.3.0` -> `3.6.17` (54 -> 8)
  - Grafana `11.3.1` -> `12.4.12` (135 -> 2)
  - Prometheus `v2.55.1` -> `v3.13.4` (98 -> 2)
- Loki's Deployment now sets `strategy: Recreate`. It holds a single-writer `ReadWriteOnce` volume, the same latent rollout problem Prometheus had.

### Verified

- AlertManager `v0.34.1`: `amtool check-config` accepts the Slack and email config, a Slack-format delivery through `api_url_file` succeeded, the image runs as UID 65534, and on the live release `PostgresExporterDown` went pending, firing (delivered) and resolved (delivered).
- Loki `3.6.17`: `-verify-config` accepts the existing config; on the live release `/ready` returned `ready`, existing data was still queryable (42 series in 24h) and Promtail was still shipping.
- Grafana `12.4.12`: scratch install and the live release both returned `OK` for the Prometheus and Loki datasources, login worked on the existing database, and the new pod's logs had no panic, fatal or error lines.
- Prometheus `v3.13.4`: `promtool check config` accepted the config and rule, the 33 MB TSDB from v2 was read (12 hourly samples in 24h), the rule showed `health=ok`, and the full firing and resolved cycle was delivered.

### Known limitations

- Image findings are not zero: PostgreSQL exporter (`v0.15.0`, 48 findings) and Promtail (`3.3.0`, 86 findings) are not yet upgraded.
- Loki's `retention_period` is set but there is no `compactor` block with `retention_enabled: true`, so retention is probably not enforced. Not yet verified on a running instance.
- Grafana 12 logs failed update and plugin checks in clusters without internet access, and a few `database is locked` retries at startup. Neither stopped the pod.
- Prometheus v3 may write TSDB blocks that v2 cannot read, so rolling back needs a data backup.

## [0.5.1] - 2026-10-03

### Changed

- Package metadata only, no chart or code changes: added PyPI `keywords`, fuller trove classifiers (audience, MIT license, topic) and `[project.urls]` (Documentation, Source, Changelog, Issues) so the package is discoverable on PyPI.

## [0.5.0] - 2026-10-02

### Added

- Dedicated zero-permission ServiceAccounts for Prometheus, Grafana, Loki, AlertManager and postgres-exporter (`templates/serviceaccounts.yaml`), with `automountServiceAccountToken: false` on both the ServiceAccounts and each Deployment's pod spec. Previously all five ran as the namespace `default` account with its API token mounted. None of them calls the Kubernetes API (Prometheus uses static targets in this chart), so no Role or RoleBinding is added. Controlled by the new `serviceAccount.create` value (default `true`). Promtail keeps its own ServiceAccount and ClusterRole, because it needs pod discovery.
- **Upgrade note:** if the release was previously upgraded with a test `--set` (for example `alertmanager.receivers.slack.enabled=true`), later upgrades keep that value. If you then delete the Secret it references, the AlertManager pod gets stuck in `ContainerCreating` after any restart. Finish such tests with `helm upgrade --reset-values` (or an explicit `--set ...=false`) before deleting the Secret.
- Configurable Grafana admin credentials: `grafana.admin.user`, `grafana.admin.password` and `grafana.admin.existingSecret` (a Secret you create, with keys `admin-user` and `admin-password`; the chart then renders no Secret of its own and the Deployment reads yours). Defaults are unchanged, so existing installs behave identically. A new `templates/NOTES.txt` prints a warning after `helm install`/`upgrade` while the placeholder password is still in use.

### Changed

- Promtail's ClusterRole now grants `get`, `list` and `watch` on `pods` only. The unused `nodes` permission was dropped: discovery uses `role: pod`, and `HOSTNAME` comes from the Downward API (`spec.nodeName`), so no Node API access is needed.

### Fixed

- The comment in `templates/grafana-secret.yaml` said to replace the password "via --set", but no value existed for `--set` to change, so it had no effect. The password is now a real value.

### Verified

- Scratch-namespace install on a live `kind` cluster (Promtail disabled): the five ServiceAccounts were created, each Deployment shows its own ServiceAccount with automount `false`, and `/var/run/secrets/kubernetes.io/serviceaccount` does not exist in the Grafana pod, which still reached Ready.
- On the long-running release (`ragleap-core` namespace, upgraded from `main` at `443ad60`): all nine Deployments (the five observability ones plus the four `ragleap-ops` ones) use their own ServiceAccount with automount `false`; `/var/run/secrets/kubernetes.io/serviceaccount` does not exist in the Prometheus pod; `up{job="ragleap-postgres"}` is 1 and AlertManager is registered as an active target; Loki kept its data across the rollout (59 series in the last 24h) and is still ingesting new logs from Promtail (2 streams for `ragleap-core` in the last 5 minutes); Promtail `/ready` returns `Ready`; the Grafana pod reached Ready without a token, and **Save & test** succeeded for both the Prometheus and Loki datasources.
- Grafana admin credentials, on a live `kind` cluster in a scratch namespace: with `--set grafana.admin.password=...` the new password returns 200 and the placeholder returns 401; with `grafana.admin.existingSecret` only the supplied Secret exists (no `ragleap-grafana-admin`) and Grafana reaches Ready; the `NOTES.txt` warning prints when neither option is set and stays empty when one is.
- Promtail with the pods-only ClusterRole, on the long-running release: `kubectl auth can-i` reports `list pods` = yes and `list nodes` = no for the Promtail ServiceAccount; no `forbidden`, `error` or `denied` lines in its logs 60 seconds after a restart; `/ready` returns `Ready`; and 2 `ragleap-core` streams were ingested into Loki in the 5 minutes after the restart.

### Known limitations

- The placeholder admin password is still the default when no option is set, and the long-running release is still using it. Upgrading will not change it: Grafana applies `GF_SECURITY_ADMIN_PASSWORD` only when it first initializes its database, so a release with a persistent volume needs `grafana cli admin reset-admin-password` (verified live: the command changed the password and the old placeholder was then rejected with 401, but it leaves the `ragleap-grafana-admin` Secret out of sync with Grafana).

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
