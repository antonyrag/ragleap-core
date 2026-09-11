# Changelog

All notable changes to `ragleap-observability` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- `postgres-exporter` had `runAsNonRoot: true` with no `runAsUser` set. The image's Dockerfile sets its user by name (`nobody`) rather than a numeric UID, which Kubernetes cannot verify against `runAsNonRoot` without an explicit numeric value -- failed on real cluster with `container has runAsNonRoot and image has non-numeric user (nobody), cannot verify user is non-root`. Fixed with `runAsUser: 65534`, confirmed via `docker run --rm --entrypoint id quay.io/prometheuscommunity/postgres-exporter:v0.15.0` (uid=65534(nobody)), not assumed. Distinct bug pattern from the earlier root-default-image issues found in `ragleap-ops` -- same root problem (runAsNonRoot needs a numeric UID) but a different underlying cause.

### Added

- Prometheus + `postgres_exporter`, step 1 of the planned build order (Prometheus/exporters first, alerting/dashboards later, per the README's own sequencing rationale -- alerting on data that doesn't exist yet is pointless).
- `neo4jExporter` config present but disabled by default -- Neo4j Community Edition Prometheus support is unverified and conflicting across sources (Neo4j's own KB and a working xk6-neo4j example show it configured successfully against Community 4.4.x; a separate monitoring vendor's compatibility notes claim Community is unsupported for their specific collector). Documented in README "Known open items", stays disabled until independently live-verified.

### Verified

- `helm lint` clean; `helm template` output confirmed exactly 3 resources render (Deployment, Service, ConfigMap), and the `neo4jExporter` scrape job is correctly absent from the rendered Prometheus config since `neo4jExporter.enabled` defaults to false.
- First live cluster deploy performed (`helm install` against a real kind cluster). `helm install` succeeded structurally with no template errors. The Prometheus ConfigMap deployed as a real object and its rendered content matched the earlier `helm template` output exactly -- only the `ragleap-postgres` scrape job present, `ragleap-neo4j` correctly absent, confirming `neo4jExporter.enabled: false` behaves identically on a real cluster, not just in template rendering. `postgres-exporter`'s pod failed exactly as pre-documented: `secret "ragleap-db-exporter-secret" not found` -- this is the already-known, already-flagged dependency gap (the read-only monitoring role does not yet exist in `ragleap-ops`'s db schema), not a new bug found by this test.

### Verified (this session)

- The `ragleap-ops` dependency is now resolved: `ragleap_monitor` role confirmed to genuinely exist in the live database via `psql -c "\\du ragleap_monitor"` (not assumed from the schema file alone), and `ragleap-db-exporter-secret` deployed successfully into the `ragleap-core` namespace.
- After the `runAsUser: 65534` fix above, `postgres-exporter` reached `1/1 Running`, 0 restarts, on a real kind cluster.
- Real end-to-end connectivity confirmed via `/metrics` endpoint (port-forwarded and curled directly, not just checked via pod status): `pg_up 1`, plus real non-zero live statistics for the `ragleap_core` database (`pg_stat_database_blks_hit`, `pg_stat_database_tup_returned`, `pg_stat_database_xact_commit`, `pg_stat_database_numbackends`, etc.) -- this is genuinely scraped data, not placeholder zeros. The exporter is proven to work end-to-end, not just "pod is green."

### Known limitations

- Neo4j Prometheus support genuinely unverified -- see Added section above. Do not enable `neo4jExporter` without independently confirming against the real `neo4j:5-community` image.
- Grafana, Loki, and AlertManager are not yet built at all -- correctly sequenced after Prometheus has real metrics flowing, per the README's own build order.
