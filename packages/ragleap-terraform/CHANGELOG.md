# Changelog

All notable changes to `ragleap-terraform` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-10-05

### Added

- `modules/kind-cluster`: creates a kind cluster and installs `ragleap-observability` through `helm_release`. Variables: `cluster_name`, `namespace`, `install_observability`, `observability_chart_path`, `grafana_admin_password` (sensitive), `install_postgres_exporter` (default `false`), `helm_timeout` (default 300) and `kubeconfig_path`.
- `examples/kind`: a working example.

### Verified

- `terraform validate` and `fmt` pass on Terraform 1.9; the example was applied on a real Docker Desktop host (Terraform 1.9.8, kind provider 0.11.0, helm provider 2.17.0): all chart pods reached Ready, and `destroy` removed the Helm release. The explicit `kubeconfig_path` kept the existing kubectl context intact.

### Known limitations

- Only a local kind cluster is covered. No AWS, GCP or Azure module exists.
- postgres-exporter is off by default: it needs `ragleap-ops`'s database and the Secret `ragleap-db-exporter-secret`, which no chart creates yet. The module does not install `ragleap-ops`.
- Interrupting `apply` or `destroy` with Ctrl+C left a cluster running with no state during testing. Do not interrupt them.
- State and the kubeconfig file contain cluster credentials in plain text.
- The `.terraform.lock.hcl` was generated on Windows; Linux hashes are not recorded.
