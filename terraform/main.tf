# =============================================================================
# VPC: тільки публічні підмережі — БЕЗ NAT Gateway.
# NAT Gateway = $0.045/год + трафік, і це найчастіша причина "тихого" рахунку.
# Для дослідницького кластера з синтетичними ворклоадами публічних підмереж
# достатньо (ноди захищені security group, API — списком CIDR).
# =============================================================================

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name = "${var.cluster_name}-vpc"
  cidr = "10.0.0.0/16"

  azs            = ["${var.region}a", "${var.region}b", "${var.region}c"]
  public_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]

  enable_nat_gateway   = false # <- ключове рішення для вартості
  enable_dns_hostnames = true
  map_public_ip_on_launch = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }
}

# =============================================================================
# EKS: spot-ноди, мінімальна конфігурація
# =============================================================================

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.24"

  cluster_name    = var.cluster_name
  cluster_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.public_subnets

  cluster_endpoint_public_access       = true
  cluster_endpoint_public_access_cidrs = var.cluster_endpoint_public_access_cidrs

  # Ніяких дорогих аддонів; тільки базові
  cluster_addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni    = {}
  }

  eks_managed_node_groups = {
    workers = {
      # SPOT — економія ~65-70% проти on-demand
      capacity_type  = "SPOT"
      instance_types = var.node_instance_types

      min_size     = 0 # можна скейлити в 0, не зносячи кластер
      desired_size = var.node_count
      max_size     = var.node_count # жорсткий стелю — автоскейлер не роздує групу

      disk_size = var.node_disk_gb
    }
  }

  # Ваш IAM-користувач (хто робить terraform apply) отримує admin на кластер
  enable_cluster_creator_admin_permissions = true
}
