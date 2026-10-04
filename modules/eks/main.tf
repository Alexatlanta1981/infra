module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = "${var.project}-${var.env}-cluster"
  kubernetes_version = var.kubernetes_version

  vpc_id     = var.vpc_id
  subnet_ids = var.subnet_ids

  endpoint_private_access = true
  endpoint_public_access  = true

  enable_irsa                              = true
  enable_cluster_creator_admin_permissions = var.enable_cluster_creator_admin

  access_entries = merge(
    var.sso_admin_role_arn == "" ? {} : {
      sso_admin = {
        principal_arn = var.sso_admin_role_arn
        policy_associations = {
          admin = {
            policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
            access_scope = { type = "cluster" }
          }
        }
      }
    },
    var.sso_readonly_role_arn == "" ? {} : {
      sso_readonly = {
        principal_arn = var.sso_readonly_role_arn
        policy_associations = {
          view = {
            policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
            access_scope = { type = "cluster" }
          }
        }
      }
    },
  )

  addons = {
    vpc-cni = {
      most_recent    = true
      before_compute = true
    }
    kube-proxy             = { most_recent = true }
    coredns                = { most_recent = true }
    eks-pod-identity-agent = { most_recent = true }
  }

  eks_managed_node_groups = {
    main = {
      instance_types = var.instance_types
      min_size       = var.min_size
      max_size       = var.max_size
      desired_size   = var.desired_size
    }
  }

  tags = {
    Project = var.project
    Env     = var.env
  }
}
