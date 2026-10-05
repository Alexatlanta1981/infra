# CI login identity (OIDC provider + Terraform plan/apply roles).
# Applied manually with admin credentials, never by the destroyable workflow.

data "aws_caller_identity" "current" {}

module "ci_oidc" {
  source = "../../modules/ci-oidc"

  project                      = "mackllc"
  env                          = "dev"
  aws_account_id               = data.aws_caller_identity.current.account_id
  infra_repo                   = "infra"
  github_repo_subject_prefixes = var.github_repo_subject_prefixes
}

# One-time adoption of roles created earlier under envs/dev. Harmless no-ops once imported.
import {
  to = module.ci_oidc.aws_iam_role.terraform_plan
  id = "mackllc-dev-terraform-plan-gha"
}
import {
  to = module.ci_oidc.aws_iam_role_policy_attachment.terraform_plan_readonly
  id = "mackllc-dev-terraform-plan-gha/arn:aws:iam::aws:policy/ReadOnlyAccess"
}
import {
  to = module.ci_oidc.aws_iam_role_policy.terraform_plan_state
  id = "mackllc-dev-terraform-plan-gha:tf-state-lock"
}
import {
  to = module.ci_oidc.aws_iam_role.terraform_apply
  id = "mackllc-dev-terraform-apply-gha"
}
import {
  to = module.ci_oidc.aws_iam_role_policy_attachment.terraform_apply_admin
  id = "mackllc-dev-terraform-apply-gha/arn:aws:iam::aws:policy/AdministratorAccess"
}
