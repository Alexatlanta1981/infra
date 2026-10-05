resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  lifecycle {
    prevent_destroy = true
  }
}

locals {
  sub_prefix = var.github_repo_subject_prefixes
}

# Terraform CI identity. Lives in envs/bootstrap (separate state) so a destroy of
# envs/dev can never remove the roles that CI uses to log in.
# plan  : any PR or main run in the infra repo, read-only
# apply : only runs from main, full permissions

data "aws_iam_policy_document" "terraform_plan_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "${local.sub_prefix[var.infra_repo]}:pull_request",
        "${local.sub_prefix[var.infra_repo]}:ref:refs/heads/main",
      ]
    }
  }
}

data "aws_iam_policy_document" "terraform_apply_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      # Apply job runs in the approval-gated "dev" environment, which changes the sub claim.
      values = ["${local.sub_prefix[var.infra_repo]}:environment:dev"]
    }
  }
}

resource "aws_iam_role" "terraform_plan" {
  lifecycle {
    prevent_destroy = true
  }

  name               = "${var.project}-${var.env}-terraform-plan-gha"
  assume_role_policy = data.aws_iam_policy_document.terraform_plan_assume.json
}

resource "aws_iam_role_policy_attachment" "terraform_plan_readonly" {
  role       = aws_iam_role.terraform_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# Plan also needs to read/lock remote state
data "aws_iam_policy_document" "terraform_plan_state" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = ["arn:aws:s3:::*terraform*", "arn:aws:s3:::*terraform*/*"]
  }

  # ReadOnlyAccess omits secret values; terraform refresh reads this project's secrets only.
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:*:${var.aws_account_id}:secret:/${var.project}/*"]
  }
}

resource "aws_iam_role_policy" "terraform_plan_state" {
  name   = "tf-state-lock"
  role   = aws_iam_role.terraform_plan.id
  policy = data.aws_iam_policy_document.terraform_plan_state.json
}

resource "aws_iam_role" "terraform_apply" {
  lifecycle {
    prevent_destroy = true
  }

  name               = "${var.project}-${var.env}-terraform-apply-gha"
  assume_role_policy = data.aws_iam_policy_document.terraform_apply_assume.json
}

# Broad on purpose for a learning project; narrow with a permissions boundary for prod
resource "aws_iam_role_policy_attachment" "terraform_apply_admin" {
  role       = aws_iam_role.terraform_apply.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
