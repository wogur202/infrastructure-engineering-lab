output "cluster_name" {
  value = aws_eks_cluster.lab.name
}
output "vpc_id" {
  value = aws_vpc.lab.id
}
output "external_ecr_repository_url" {
  value = data.aws_ecr_repository.existing.repository_url
}
output "budget_reminder" {
  value = "USD ${var.lab_budget_usd}; stop new tests at ${var.max_lab_hours}h, then export and clean up. Not an enforced billing cap."
}
