output "cluster_name" {
  value = module.eks.cluster_name
}

output "kubeconfig_command" {
  description = "Команда для налаштування kubectl (для вас і для Claude Code)"
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}

output "claude_code_access_key_id" {
  value = aws_iam_access_key.claude_code.id
}

output "claude_code_secret_access_key" {
  value     = aws_iam_access_key.claude_code.secret
  sensitive = true
  # Дістати: terraform output -raw claude_code_secret_access_key
}

output "estimated_hourly_cost_usd" {
  value = "~0.25 USD/год (control plane 0.10 + 3x spot m5.large ~0.11 + EBS ~0.01). Повний день ~6 USD."
}
