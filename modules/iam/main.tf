locals {
  # Kubernetes service account name == component name; one IAM role per microservice
  microservices = toset([
    "api-gateway", "auth-service", "drug-catalog-service", "inventory-service",
    "manufacturing-service", "notification-service", "pharma-ui", "qc-service",
    "supplier-service",
  ])
  # Argo CD runs once per environment; Helm renders inside repo-server and
  # deploys via the controller, so both inherit the Argo CD identity.
  argocd_envs  = toset(["dev", "qa", "prod"])
  secrets_read = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
  alb_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["iam:CreateServiceLinkedRole"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "iam:AWSServiceName" = "elasticloadbalancing.amazonaws.com"
          }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeAccountAttributes",
          "ec2:DescribeAddresses",
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeInternetGateways",
          "ec2:DescribeVpcs",
          "ec2:DescribeVpcPeeringConnections",
          "ec2:DescribeSubnets",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeInstances",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeTags",
          "ec2:GetCoipPoolUsage",
          "ec2:DescribeCoipPools",
          "ec2:GetSecurityGroupsForVpc",
          "ec2:DescribeIpamPools",
          "ec2:DescribeRouteTables",
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticloadbalancing:DescribeLoadBalancerAttributes",
          "elasticloadbalancing:DescribeListeners",
          "elasticloadbalancing:DescribeListenerCertificates",
          "elasticloadbalancing:DescribeSSLPolicies",
          "elasticloadbalancing:DescribeRules",
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DescribeTargetGroupAttributes",
          "elasticloadbalancing:DescribeTargetHealth",
          "elasticloadbalancing:DescribeTags",
          "elasticloadbalancing:DescribeTrustStores",
          "elasticloadbalancing:DescribeListenerAttributes",
          "elasticloadbalancing:DescribeCapacityReservation"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "cognito-idp:DescribeUserPoolClient",
          "acm:ListCertificates",
          "acm:DescribeCertificate",
          "iam:ListServerCertificates",
          "iam:GetServerCertificate",
          "waf-regional:GetWebACL",
          "waf-regional:GetWebACLForResource",
          "waf-regional:AssociateWebACL",
          "waf-regional:DisassociateWebACL",
          "wafv2:GetWebACL",
          "wafv2:GetWebACLForResource",
          "wafv2:AssociateWebACL",
          "wafv2:DisassociateWebACL",
          "shield:GetSubscriptionState",
          "shield:DescribeProtection",
          "shield:CreateProtection",
          "shield:DeleteProtection"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:CreateSecurityGroup",
          "ec2:CreateTags",
          "ec2:DeleteTags",
          "ec2:DeleteSecurityGroup",
          "ec2:ModifyNetworkInterfaceAttribute"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:CreateLoadBalancer",
          "elasticloadbalancing:CreateTargetGroup",
          "elasticloadbalancing:CreateListener",
          "elasticloadbalancing:DeleteListener",
          "elasticloadbalancing:CreateRule",
          "elasticloadbalancing:DeleteRule",
          "elasticloadbalancing:AddTags",
          "elasticloadbalancing:RemoveTags",
          "elasticloadbalancing:ModifyLoadBalancerAttributes",
          "elasticloadbalancing:SetIpAddressType",
          "elasticloadbalancing:SetSecurityGroups",
          "elasticloadbalancing:SetSubnets",
          "elasticloadbalancing:DeleteLoadBalancer",
          "elasticloadbalancing:ModifyTargetGroup",
          "elasticloadbalancing:ModifyTargetGroupAttributes",
          "elasticloadbalancing:DeleteTargetGroup",
          "elasticloadbalancing:ModifyListenerAttributes",
          "elasticloadbalancing:ModifyCapacityReservation",
          "elasticloadbalancing:RegisterTargets",
          "elasticloadbalancing:DeregisterTargets",
          "elasticloadbalancing:SetWebAcl",
          "elasticloadbalancing:ModifyListener",
          "elasticloadbalancing:AddListenerCertificates",
          "elasticloadbalancing:RemoveListenerCertificates",
          "elasticloadbalancing:ModifyRule"
        ]
        Resource = "*"
      }
    ]
  })
  alb_boundary = ["acm:*", "cognito-idp:*", "ec2:*", "elasticloadbalancing:*", "iam:CreateServiceLinkedRole", "iam:GetServerCertificate", "iam:ListServerCertificates", "shield:*", "waf-regional:*", "wafv2:*"]
}

# ─── Platform add-ons (IRSA) ────────────────────────────────────────────────
module "eso" {
  source            = "../irsa-role"
  project           = var.project
  env               = var.env
  component         = "eso"
  oidc_provider_arn = var.oidc_provider_arn
  oidc_provider_url = var.oidc_provider_url
  service_accounts  = ["external-secrets/external-secrets"]
  policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = local.secrets_read
      Resource = [
        "arn:aws:secretsmanager:*:${var.aws_account_id}:secret:/pharma/*",
        "arn:aws:secretsmanager:*:${var.aws_account_id}:secret:rds!db-*"
      ]
    }]
  })
  boundary_allowed_actions = local.secrets_read
}

module "alb_controller" {
  source                   = "../irsa-role"
  project                  = var.project
  env                      = var.env
  component                = "alb-controller"
  oidc_provider_arn        = var.oidc_provider_arn
  oidc_provider_url        = var.oidc_provider_url
  service_accounts         = ["kube-system/aws-load-balancer-controller"]
  policy_json              = local.alb_policy
  boundary_allowed_actions = local.alb_boundary
}

# One Argo CD role per environment. Needs no AWS API access (ECR pulls use
# node/IRSA of workloads), so the boundary only allows ECR read.
module "argocd" {
  for_each          = local.argocd_envs
  source            = "../irsa-role"
  project           = var.project
  env               = each.key
  component         = "argocd"
  oidc_provider_arn = var.oidc_provider_arn
  oidc_provider_url = var.oidc_provider_url
  service_accounts = [
    "argocd/argocd-application-controller",
    "argocd/argocd-repo-server",
    "argocd/argocd-server",
  ]
  policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ecr:GetAuthorizationToken"]
      Resource = "*"
    }]
  })
  boundary_allowed_actions = ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
}

# ─── One role / trust / boundary / policy per microservice ──────────────────
module "microservice" {
  for_each          = local.microservices
  source            = "../irsa-role"
  project           = var.project
  env               = var.env
  component         = each.key
  oidc_provider_arn = var.oidc_provider_arn
  oidc_provider_url = var.oidc_provider_url
  service_accounts  = ["${var.env}/${each.key}"]
  policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = local.secrets_read
      Resource = "arn:aws:secretsmanager:*:${var.aws_account_id}:secret:/pharma/${var.env}/${each.key}/*"
    }]
  })
  boundary_allowed_actions = local.secrets_read
}
