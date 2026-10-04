resource "kind_cluster" "this" {
  name            = var.cluster_name
  wait_for_ready  = true
  kubeconfig_path = var.kubeconfig_path
}

provider "helm" {
  kubernetes {
    host                   = kind_cluster.this.endpoint
    cluster_ca_certificate = kind_cluster.this.cluster_ca_certificate
    client_certificate     = kind_cluster.this.client_certificate
    client_key             = kind_cluster.this.client_key
  }
}

resource "helm_release" "observability" {
  count            = var.install_observability ? 1 : 0
  name             = "ragleap-observability"
  chart            = var.observability_chart_path
  namespace        = var.namespace
  create_namespace = true
  timeout          = var.helm_timeout

  values = concat(
    [yamlencode({ postgresExporter = { enabled = var.install_postgres_exporter } })],
    var.grafana_admin_password == "" ? [] : [
      yamlencode({ grafana = { admin = { password = var.grafana_admin_password } } })
    ]
  )

  # Promtail owns cluster-scoped RBAC with fixed names; keep it on for a clean cluster.
  depends_on = [kind_cluster.this]
}
