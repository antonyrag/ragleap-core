variable "cluster_name" {
  description = "Name of the kind cluster. Pick one that does not clash with an existing cluster."
  type        = string
  default     = "ragleap-tf"
}

variable "namespace" {
  description = "Namespace the RagLeap charts are installed into."
  type        = string
  default     = "ragleap-core"
}

variable "install_observability" {
  description = "Install the ragleap-observability chart."
  type        = bool
  default     = true
}

variable "observability_chart_path" {
  description = "Path to the ragleap-observability Helm chart directory."
  type        = string
  default     = ""
}

variable "grafana_admin_password" {
  description = "Grafana admin password. Empty falls back to the chart's placeholder, which is not safe beyond a local test."
  type        = string
  default     = ""
  sensitive   = true
}

variable "install_postgres_exporter" {
  description = "Deploy postgres-exporter. Needs ragleap-db and the Secret ragleap-db-exporter-secret to exist first, so it is off by default."
  type        = bool
  default     = false
}

variable "helm_timeout" {
  description = "Seconds to wait for the Helm release to become ready."
  type        = number
  default     = 300
}

variable "kubeconfig_path" {
  description = "Where the kind provider writes this cluster's kubeconfig. Null uses the provider default."
  type        = string
  default     = null
}
