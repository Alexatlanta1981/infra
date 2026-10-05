# ─── GitHub Actions OIDC (CI pushes to ECR, no static keys) ─────────────────

# Provider is owned by envs/bootstrap so destroying this env never removes CI login.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
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
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
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
