variable "project" {
  description = "Project name"
  type        = string
}

variable "env" {
  description = "Environment name (dev, qa, prod)"
  type        = string
}

variable "oidc_provider_arn" {
  description = "ARN of the EKS OIDC provider"
  type        = string
}

variable "oidc_provider_url" {
  description = "URL of the EKS OIDC provider"
  type        = string
}

variable "aws_account_id" {
  description = "AWS Account ID"
  type        = string
}

variable "github_org" {
  description = "GitHub organization or username that owns frontend and backend"
  type        = string
}

variable "infra_repo" {
  description = "Name of the infra repository that runs Terraform in GitHub Actions"
  type        = string
  default     = "infra"
}

variable "github_repo_subject_prefixes" {
  description = "Map of repo name to its OIDC sub-claim prefix (see /actions/oidc/customization/sub)"
  type        = map(string)
}
