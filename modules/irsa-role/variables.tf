variable "project" { type = string }
variable "env" { type = string }

variable "component" {
  description = "Workload name, lowercase kebab-case (e.g. auth-service, argocd, eso)"
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,40}$", var.component))
    error_message = "component must be lowercase kebab-case."
  }
}

variable "oidc_provider_arn" { type = string }
variable "oidc_provider_url" { type = string }

variable "service_accounts" {
  description = "Kubernetes service accounts allowed to assume the role, as namespace/name"
  type        = list(string)
}

variable "policy_json" {
  description = "Permission policy (least privilege) attached to the role"
  type        = string
}

variable "boundary_allowed_actions" {
  description = "Permission boundary ceiling: the only actions the role can ever use"
  type        = list(string)
}
