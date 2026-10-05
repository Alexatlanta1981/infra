# CI roles now live in envs/bootstrap. Drop from this state without deleting in AWS.
removed {
  from = module.iam.aws_iam_role.terraform_plan
  lifecycle { destroy = false }
}
removed {
  from = module.iam.aws_iam_role_policy_attachment.terraform_plan_readonly
  lifecycle { destroy = false }
}
removed {
  from = module.iam.aws_iam_role_policy.terraform_plan_state
  lifecycle { destroy = false }
}
removed {
  from = module.iam.aws_iam_role.terraform_apply
  lifecycle { destroy = false }
}
removed {
  from = module.iam.aws_iam_role_policy_attachment.terraform_apply_admin
  lifecycle { destroy = false }
}
