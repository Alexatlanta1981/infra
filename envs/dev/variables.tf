variable "db_password" {
  description = "Master password for the RDS PostgreSQL database"
  type        = string
  sensitive   = true
}

variable "jwt_secret" {
  description = "JWT signing secret for the application"
  type        = string
  sensitive   = true
}

variable "github_org" {
  description = "GitHub username or organization that owns frontend and backend"
  type        = string
  default     = "mackllc"
}

variable "infra_repo" {
  description = "Name of the infra repo that runs Terraform in GitHub Actions"
  type        = string
  default     = "infra"
}

variable "sso_admin_role_arn" {
  description = "IAM Identity Center admin role ARN (no aws-reserved path). Empty to skip."
  type        = string
  default     = ""
}

variable "sso_readonly_role_arn" {
  description = "IAM Identity Center read-only role ARN (no aws-reserved path). Empty to skip."
  type        = string
  default     = ""
}

variable "enable_cluster_creator_admin" {
  description = "Keep permanent admin for the cluster creator. Set false once SSO access works."
  type        = bool
  default     = true
}
