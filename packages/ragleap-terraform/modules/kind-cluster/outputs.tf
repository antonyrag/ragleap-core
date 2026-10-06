output "cluster_name" {
  value = kind_cluster.this.name
}

output "kubeconfig_path" {
  description = "Path of the kubeconfig the kind provider wrote."
  value       = kind_cluster.this.kubeconfig_path
}
