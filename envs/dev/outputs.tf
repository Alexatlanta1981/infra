output "rds_endpoint" {
  description = "RDS instance endpoint"
  value       = module.rds.db_instance_endpoint
}

output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "github_actions_role_arn" {
  description = "GitHub Actions OIDC role ARN"
  value       = module.iam.github_actions_role_arn
}

output "terraform_plan_role_arn" {
  description = "Set as repo variable AWS_TF_PLAN_ROLE_ARN"
  value       = module.iam.terraform_plan_role_arn
}

output "terraform_apply_role_arn" {
  description = "Set as repo variable AWS_TF_APPLY_ROLE_ARN"
  value       = module.iam.terraform_apply_role_arn
}
