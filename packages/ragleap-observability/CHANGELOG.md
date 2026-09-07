# Changelog

All notable changes to `ragleap-observability` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Prometheus + `postgres_exporter`, step 1 of the planned build order (Prometheus/exporters first, alerting/dashboards later, per the README's own sequencing rationale -- alerting on data that doesn't exist yet is pointless).
- `neo4jExporter` config present but disabled by default -- Neo4j Community Edition Prometheus support is unverified and conflicting across sources (Neo4j's own KB and a working xk6-neo4j example show it configured successfully against Community 4.4.x; a separate monitoring vendor's compatibility notes claim Community is unsupported for their specific collector). Documented in README "Known open items", stays disabled until independently live-verified.

### Verified

- `helm lint` clean; `helm template` output confirmed exactly 3 resources render (Deployment, Service, ConfigMap), and the `neo4jExporter` scrape job is correctly absent from the rendered Prometheus config since `neo4jExporter.enabled` defaults to false.
- First live cluster deploy performed (`helm install` against a real kind cluster). `helm install` succeeded structurally with no template errors. The Prometheus ConfigMap deployed as a real object and its rendered content matched the earlier `helm template` output exactly -- only the `ragleap-postgres` scrape job present, `ragleap-neo4j` correctly absent, confirming `neo4jExporter.enabled: false` behaves identically on a real cluster, not just in template rendering. `postgres-exporter`'s pod failed exactly as pre-documented: `secret "ragleap-db-exporter-secret" not found` -- this is the already-known, already-flagged dependency gap (the read-only monitoring role does not yet exist in `ragleap-ops`'s db schema), not a new bug found by this test.

### Known limitations

- `postgres_exporter` cannot actually connect to a real database yet -- `ragleap-db`'s schema does not have a read-only monitoring role, and no `ragleap-db-exporter-secret` exists. This is a real, tracked dependency on `ragleap-ops`, not yet resolved.
- Neo4j Prometheus support genuinely unverified -- see Added section above. Do not enable `neo4jExporter` without independently confirming against the real `neo4j:5-community` image.
- Grafana, Loki, and AlertManager are not yet built at all -- correctly sequenced after Prometheus has real metrics flowing, per the README's own build order.
