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
  default     = "arn:aws:iam::058170692253:role/AWSReservedSSO_ConsoleAdministratorAccess_7cbcf4d5e2367bb5"
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

variable "github_repo_subject_prefixes" {
  description = "Map of repo name to its OIDC sub-claim prefix"
  type        = map(string)
  default = {
    infra    = "repo:Alexatlanta1981@336695319/infra@1392205632"
    backend  = "repo:Alexatlanta1981@336695319/backend@1391441917"
    frontend = "repo:Alexatlanta1981@336695319/frontend@1391441426"
    gitops   = "repo:Alexatlanta1981@336695319/gitops@1392209866"
  }
}
