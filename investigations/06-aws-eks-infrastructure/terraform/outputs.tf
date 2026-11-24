output "public_subnet_ids" {
  description = "Public subnet IDs for the ALB Ingress"
  value = [
    aws_subnet.public["a"].id,
    aws_subnet.public["c"].id
  ]
}
