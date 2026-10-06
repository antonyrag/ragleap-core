module "ragleap" {
  source                   = "../../modules/kind-cluster"
  cluster_name             = "ragleap-tf"
  kubeconfig_path          = abspath("${path.module}/ragleap-tf-config")
  observability_chart_path = "${path.module}/../../../ragleap-observability/helm/ragleap-observability"
}

output "kubeconfig_path" {
  value = module.ragleap.kubeconfig_path
}
