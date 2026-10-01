# ragleap-observability

Metrics, logs, and alerting for RagLeap Core -- Prometheus, Grafana,
Loki, and AlertManager, wired against the real db/app/voice/neo4j
services.

## Status

Prometheus + `postgres_exporter`, Grafana, Loki + Promtail, and
AlertManager are all built and live-verified end-to-end against a
real cluster:

- `postgres_exporter` connects to `ragleap-db` using a read-only
  monitoring role; `/metrics` returns real, non-zero PostgreSQL
  statistics (`pg_up 1`, live `pg_stat_database` values).
- Grafana's Prometheus and Loki datasources are both confirmed live
  through Grafana's own datasource proxy, not just "pod is Running."
- Loki + Promtail log shipping is proven end-to-end: 21+ real log
  streams confirmed in Loki with correct `namespace`/`pod`/`container`
  labels, spanning nearly every pod in the cluster. See CHANGELOG for
  the full diagnostic history -- several real, non-obvious bugs (a
  cross-namespace DNS lookup, a Kubernetes service-discovery `__path__`
  resolution issue, and a YAML document-boundary corruption) were
  found and fixed to get here.
- AlertManager is wired end-to-end to Prometheus and live-verified:
  Prometheus's own `/api/v1/alertmanagers` confirms it as a genuinely
  registered target, and a real first alert rule (`PostgresExporterDown`)
  loads correctly. **Optional Slack and email receivers are supported but
  off by default** (`alertmanager.receivers.*` in `values.yaml`);
  credentials come from a Secret you create, never from values. Until
  you enable one, alerts go to a placeholder webhook and nothing notifies
  a human. Firing and resolved delivery were verified end to end on a live
  cluster against a Slack-compatible stand-in; a real Slack/email
  send has not yet been confirmed.

SLO/SLI dashboards are not yet built -- correctly sequenced after
alerting has proven reliable, per the build order below.

## Planned build order

1. Prometheus + exporters (postgres_exporter for db) -- done,
   live-verified. neo4j's exporter remains disabled pending
   independent verification, see "Known open items".
2. Grafana, provisioned dashboards-as-code, verified against real
   flowing data -- done, live-verified.
3. Loki + log shipping -- done, live-verified end-to-end.
4. AlertManager -- done, wired and live-verified. Slack/email
   receivers available but off by default; see "Known open items".
5. SLO/SLI dashboards, only after real data has accumulated for days,
   not minutes

## Design principles

- RagLeap-specific scoping, same honest choice `ragleap-ops` made for
  itself -- not a generic monitoring tool
- Every claim live-verified against a real cluster or explicitly
  labeled unverified, same discipline as every other package here

## Known open items

- **Neo4j Prometheus support is unverified and conflicting in the wild.**
  Neo4j's own KB and a working xk6-neo4j example show
  `metrics.prometheus.enabled=true` configured successfully against
  Neo4j Community 4.4.x. A separate monitoring vendor's own
  compatibility notes claim Community Edition is unsupported for their
  specific collector. `neo4jExporter.enabled` defaults to `false` in
  `values.yaml` until this is live-verified against the real
  `neo4j:5-community` image in this repo's own `kind` cluster.
- Loki's retention (`168h` / 7 days) is unverified for real
  storage-sizing needs; flagged in `values.yaml` as a placeholder.
- **AlertManager receivers are off by default, and a real Slack/email
  send is unconfirmed** (delivery is verified against a stand-in). Enable `alertmanager.receivers.slack` and/or `.email` and
  create the Secret named in `values.yaml`. Until then alerts are routed
  and grouped but go to a placeholder webhook. PagerDuty is not
  supported yet.
- AlertManager's state (silences, notification log) uses `emptyDir`,
  not a PVC -- lost on pod restart.
- A recurring log-shipping health check remains unbuilt.
- No canary or blue-green deployment strategy exists in this project
  -- every Deployment uses the Kubernetes default `RollingUpdate` or,
  for Prometheus specifically, an explicit `Recreate` (required by its
  single-writer TSDB storage). Correctly sequenced after GitOps
  tooling (ArgoCD/Flux), which has not been started.
