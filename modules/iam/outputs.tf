output "eso_role_arn" {
  value = module.eso.role_arn
}

output "alb_controller_role_arn" {
  value = module.alb_controller.role_arn
}

output "argocd_role_arns" {
  description = "Argo CD role ARN per environment (dev, stage, prod)"
  value       = { for k, m in module.argocd : k => m.role_arn }
}

output "microservice_role_arns" {
  description = "IRSA role ARN per microservice; annotate each service account with its ARN"
  value       = { for k, m in module.microservice : k => m.role_arn }
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}

output "terraform_plan_role_arn" {
  value = aws_iam_role.terraform_plan.arn
}

output "terraform_apply_role_arn" {
  value = aws_iam_role.terraform_apply.arn
}
