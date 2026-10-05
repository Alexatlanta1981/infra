# ─── GitHub Actions OIDC (CI pushes to ECR, no static keys) ─────────────────

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

locals {
  # Repos use immutable OIDC subjects (org@id/repo@id), so trust must match those exactly.
  sub_prefix = var.github_repo_subject_prefixes
}

data "aws_iam_policy_document" "github_actions_assume" {
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
        "${local.sub_prefix["backend"]}:ref:refs/heads/main",
        "${local.sub_prefix["backend"]}:ref:refs/heads/develop",
        "${local.sub_prefix["backend"]}:ref:refs/heads/release/*",
        "${local.sub_prefix["frontend"]}:ref:refs/heads/main",
        "${local.sub_prefix["frontend"]}:ref:refs/heads/develop",
        "${local.sub_prefix["frontend"]}:ref:refs/heads/release/*",
        "${local.sub_prefix["backend"]}:environment:*",
        "${local.sub_prefix["frontend"]}:environment:*",
      ]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${var.project}-${var.env}-ecr-push-gha"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume.json
}

data "aws_iam_policy_document" "github_actions_ecr" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = ["arn:aws:ecr:*:${var.aws_account_id}:repository/*"]
  }
}

resource "aws_iam_role_policy" "github_actions_ecr" {
  name   = "ecr-push"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_ecr.json
}

# ─── GitHub Actions OIDC for Terraform (replaces static AWS keys) ───────────
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
      values   = ["${local.sub_prefix[var.infra_repo]}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "terraform_plan" {
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
  name               = "${var.project}-${var.env}-terraform-apply-gha"
  assume_role_policy = data.aws_iam_policy_document.terraform_apply_assume.json
}

# Broad on purpose for a learning project; narrow with a permissions boundary for prod
resource "aws_iam_role_policy_attachment" "terraform_apply_admin" {
  role       = aws_iam_role.terraform_apply.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
