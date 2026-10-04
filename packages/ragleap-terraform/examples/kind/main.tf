module "ragleap" {
  source                   = "../../modules/kind-cluster"
  cluster_name             = "ragleap-tf"
  observability_chart_path = "${path.module}/../../../ragleap-observability/helm/ragleap-observability"
}

output "kubeconfig_path" {
  value = module.ragleap.kubeconfig_path
}
