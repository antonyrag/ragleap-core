# Changelog

All notable changes to `ragleap-observability` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
- **Cross-namespace DNS lookup failure in Promtail's Loki client.** The client URL used a bare service name (`ragleap-loki`), which only resolves via CoreDNS's `kubernetes` plugin within the querying pod's own namespace. Since Promtail runs in `ragleap-observability-agents` and Loki runs in `ragleap-core`, every push failed with `dial tcp: lookup ragleap-loki ... server misbehaving`. Symptom looked exactly like a CoreDNS health problem but a full CoreDNS restart did not fix it. Fixed by switching to `ragleap-loki.{{ .Release.Namespace }}.svc.cluster.local`.
- **`kubernetes_sd_configs` produced 0 active targets despite correct discovery.** Root-caused through several layers: (1) Promtail auto-injects a node-scoping field selector built from `$HOSTNAME`, which without an explicit override defaults to the pod's own name rather than the real node name -- fixed by setting `HOSTNAME` via the Downward API. (2) A hand-built multi-capture-group regex for `__path__` matched real on-disk paths exactly by hand, yet Promtail's own `/ready` endpoint still reported "unable to find any logs to tail" -- replaced with Grafana's own canonical production pattern (`__meta_kubernetes_pod_uid` + `__meta_kubernetes_pod_container_name` joined by a literal `/` separator, default single-capture regex, wrapped in `/var/log/pods/*$1/*.log`). Also added the `cri: {}` pipeline stage needed to correctly parse Kubernetes' CRI log line format.
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
