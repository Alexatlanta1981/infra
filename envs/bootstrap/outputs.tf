output "terraform_plan_role_arn" {
  description = "Set as repo variable AWS_TF_PLAN_ROLE_ARN"
  value       = module.ci_oidc.terraform_plan_role_arn
}

output "terraform_apply_role_arn" {
  description = "Set as repo variable AWS_TF_APPLY_ROLE_ARN"
  value       = module.ci_oidc.terraform_apply_role_arn
}
