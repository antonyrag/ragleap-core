# ragleap-observability

Metrics, logs, and alerting for RagLeap Core -- Prometheus, Grafana,
Loki, and AlertManager, wired against the real db/app/voice/neo4j
services.

## Status

Prometheus + `postgres_exporter` are built and live-verified end-to-end
against a real cluster: the exporter connects to `ragleap-db` using a
read-only monitoring role, and `/metrics` returns real, non-zero
PostgreSQL statistics (`pg_up 1`, live `pg_stat_database` values). This
is the prerequisite for AIOps per the project's own DevOps maturity
roadmap -- building anomaly detection before a metrics pipeline exists
would be "a dashboard for data that doesn't exist."

Grafana, Loki, and AlertManager are not yet built -- correctly
sequenced after Prometheus has proven real metrics flowing, per the
build order below.

## Planned build order

1. ✅ Prometheus + exporters (postgres_exporter for db) -- done,
   live-verified this session. neo4j's exporter remains disabled
   pending independent verification, see "Known open items".
2. Grafana, provisioned dashboards-as-code, verified against real
   flowing data
3. Loki + log shipping (can parallel step 2)
4. AlertManager -- deliberately last; alerting on data that doesn't
   exist yet is pointless
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
- ~~`ragleap-db`'s schema does not yet have a read-only monitoring role~~
  **Resolved and live-verified this session.** The `ragleap_monitor`
  role exists in `ragleap-ops`'s schema and `ragleap-db-exporter-secret`
  connects successfully -- confirmed via real `/metrics` output showing
  `pg_up 1` and live PostgreSQL statistics, not just a running pod.
