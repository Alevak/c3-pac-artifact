# =============================================================================
# IAM для Claude Code: ПРИНЦИП — агент НЕ МОЖЕ створювати AWS-ресурси.
#
# Claude Code отримує:
#   1. eks:DescribeCluster — тільки щоб згенерувати kubeconfig
#   2. Admin ВСЕРЕДИНІ кластера (через EKS Access Entry) — деплой ворклоадів,
#      Gatekeeper, збір метрик
#
# Claude Code НЕ отримує: ec2:*, iam:*, s3:* (створення), autoscaling:* тощо.
# Максимальна шкода агента = завалити кластер зсередини. Рахунок від цього
# не зросте: ноди обмежені max_size, нових створити він не може.
# =============================================================================

resource "aws_iam_user" "claude_code" {
  name = "${var.cluster_name}-claude-code"
}

resource "aws_iam_user_policy" "claude_code_eks_describe" {
  name = "eks-describe-only"
  user = aws_iam_user.claude_code.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DescribeClusterForKubeconfig"
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster", "eks:ListClusters"]
        Resource = module.eks.cluster_arn
      },
      {
        # Явна заборона всього дорогого — навіть якщо хтось колись
        # причепить цьому користувачу ширшу політику
        Sid    = "HardDenyExpensive"
        Effect = "Deny"
        Action = [
          "ec2:RunInstances",
          "ec2:CreateNatGateway",
          "eks:CreateCluster",
          "eks:CreateNodegroup",
          "eks:UpdateNodegroupConfig",
          "autoscaling:*",
          "iam:Create*",
          "iam:Attach*",
          "iam:Put*",
          "rds:*",
          "sagemaker:*",
          "bedrock:*"
        ]
        Resource = "*"
      }
    ]
  })
}

# Кластерний доступ: admin усередині Kubernetes (не в AWS-акаунті)
resource "aws_eks_access_entry" "claude_code" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_user.claude_code.arn
}

resource "aws_eks_access_policy_association" "claude_code_admin" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_user.claude_code.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}

# Access key для Claude Code — з'явиться в terraform output (sensitive)
resource "aws_iam_access_key" "claude_code" {
  user = aws_iam_user.claude_code.name
}
