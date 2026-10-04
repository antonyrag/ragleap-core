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
