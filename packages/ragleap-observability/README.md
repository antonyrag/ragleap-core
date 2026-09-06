# ragleap-observability

Metrics, logs, and alerting for RagLeap Core -- Prometheus, Grafana,
Loki, and AlertManager, wired against the real db/app/voice/neo4j
services.

## Status

Design/scaffold only. No Helm chart content yet. This is the
prerequisite for AIOps per the project's own DevOps maturity roadmap --
building anomaly detection before a metrics pipeline exists would be
"a dashboard for data that doesn't exist."

## Planned build order

1. Prometheus + exporters (postgres_exporter for db; verify neo4j's
   Prometheus endpoint exists in Community Edition before assuming --
   same discipline as the backup-command check in ragleap-ops)
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
