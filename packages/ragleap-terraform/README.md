# ragleap-terraform

Terraform module that creates a local [kind](https://kind.sigs.k8s.io) cluster and installs the RagLeap Helm charts onto it. Tested on a real cluster; no cloud modules yet.

## Usage

The `.tf` files ship in the wheel under `ragleap_terraform/modules` and `ragleap_terraform/examples`, and in the repo under `packages/ragleap-terraform/`.

```bash
cd packages/ragleap-terraform/examples/kind
terraform init
terraform apply
```

Requires Docker, Terraform >= 1.5 and the `ragleap-observability` chart (the example points at the repo copy).

## Variables

- `cluster_name` (default `ragleap-tf`), `namespace` (default `ragleap-core`)
- `install_observability` (default `true`), `observability_chart_path`
- `grafana_admin_password` (sensitive; empty uses the chart's placeholder, which is not safe beyond a local test)
- `install_postgres_exporter` (default `false`, see below)
- `helm_timeout` (seconds, default 300), `kubeconfig_path`

## Known limitations

- **postgres-exporter is off by default.** It needs the `ragleap-ops` database and the Secret `ragleap-db-exporter-secret`. No chart creates that Secret yet, and this module does not install `ragleap-ops`.
- **Credentials:** `terraform.tfstate` and the generated kubeconfig contain cluster credentials in plain text. Never commit them.
- **Never press Ctrl+C during `apply` or `destroy`.** During testing it left a cluster running with no state. Check `terraform state list` before deleting state files.
- If a cluster is left behind: `kind delete cluster --name ragleap-tf`.
- Always set `kubeconfig_path` so your own kubectl context is not touched.
