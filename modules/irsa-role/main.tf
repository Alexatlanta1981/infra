# Naming convention: <project>-<env>-<component>-<type>
#   role     -> pharma-dev-auth-service-irsa
#   policy   -> pharma-dev-auth-service-policy
#   boundary -> pharma-dev-auth-service-boundary
locals {
  base    = "${var.project}-${var.env}-${var.component}"
  issuer  = replace(var.oidc_provider_url, "https://", "")
  tags    = { Project = var.project, Env = var.env, Component = var.component, ManagedBy = "terraform" }
  sa_subs = [for sa in var.service_accounts : "system:serviceaccount:${sa}"]
}

# Trust policy: only the named service accounts, via the cluster OIDC provider
data "aws_iam_policy_document" "trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.issuer}:sub"
      values   = local.sa_subs
    }
    condition {
      test     = "StringEquals"
      variable = "${local.issuer}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

# Permission boundary: ceiling on permissions, plus a hard deny on IAM users/keys
data "aws_iam_policy_document" "boundary" {
  statement {
    sid       = "Ceiling"
    effect    = "Allow"
    actions   = var.boundary_allowed_actions
    resources = ["*"]
  }
  statement {
    sid    = "NoIamUsersOrKeys"
    effect = "Deny"
    actions = [
      "iam:CreateUser", "iam:CreateAccessKey", "iam:CreateLoginProfile",
      "iam:UpdateLoginProfile", "iam:AttachUserPolicy", "iam:PutUserPolicy",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "boundary" {
  name   = "${local.base}-boundary"
  policy = data.aws_iam_policy_document.boundary.json
  tags   = local.tags
}

resource "aws_iam_role" "this" {
  name                 = "${local.base}-irsa"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  permissions_boundary = aws_iam_policy.boundary.arn
  max_session_duration = 3600
  tags                 = local.tags
}

resource "aws_iam_policy" "this" {
  name   = "${local.base}-policy"
  policy = var.policy_json
  tags   = local.tags
}

resource "aws_iam_role_policy_attachment" "this" {
  role       = aws_iam_role.this.name
  policy_arn = aws_iam_policy.this.arn
}
