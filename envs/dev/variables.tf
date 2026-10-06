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
  description = "IAM Identity Center admin role ARN (full ARN incl. aws-reserved path). Empty to skip."
  type        = string
  default     = ""
}

variable "sso_readonly_role_arn" {
  description = "IAM Identity Center read-only role ARN (full ARN incl. aws-reserved path). Empty to skip."
  type        = string
  default     = ""
}

variable "enable_cluster_creator_admin" {
  description = "Keep permanent admin for the cluster creator. Set false once SSO access works."
  type        = bool
  default     = true
}

variable "github_repo_subject_prefixes" {
  description = "Map of repo name to its OIDC sub-claim prefix, e.g. repo:ORG@ORGID/infra@REPOID per repo. Generate with scripts/00_oidc_subjects.sh"
  type        = map(string)
}
