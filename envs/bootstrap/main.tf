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
