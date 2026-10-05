output "oidc_provider_arn" { value = aws_iam_openid_connect_provider.github.arn }
output "terraform_plan_role_arn" { value = aws_iam_role.terraform_plan.arn }
output "terraform_apply_role_arn" { value = aws_iam_role.terraform_apply.arn }
