variable "project" {
  description = "Project name"
  type        = string
}

variable "env" {
  description = "Environment name (dev, qa, prod)"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for the EKS cluster"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for EKS nodes"
  type        = list(string)
}

variable "kubernetes_version" {
  description = "Kubernetes version for the EKS cluster"
  type        = string
  default     = "1.33"
}

variable "instance_types" {
  description = "EC2 instance types for the node group"
  type        = list(string)
  default     = ["t3.medium"]
}

variable "desired_size" {
  description = "Desired number of worker nodes"
  type        = number
  default     = 2
}

variable "min_size" {
  description = "Minimum number of worker nodes"
  type        = number
  default     = 1
}

variable "max_size" {
  description = "Maximum number of worker nodes"
  type        = number
  default     = 3
}

variable "enable_cluster_creator_admin" {
  description = "Give the identity that created the cluster permanent admin. Turn off once SSO access is working."
  type        = bool
  default     = true
}

variable "sso_admin_role_arn" {
  description = "IAM Identity Center (SSO) admin role ARN, WITHOUT the aws-reserved/sso.amazonaws.com path. Empty to skip."
  type        = string
  default     = ""
}

variable "sso_readonly_role_arn" {
  description = "IAM Identity Center (SSO) read-only role ARN, WITHOUT the aws-reserved/sso.amazonaws.com path. Empty to skip."
  type        = string
  default     = ""
}
