resource "aws_eks_cluster" "main" {
  name     = "aegis-eks"
  role_arn = aws_iam_role.eks_cluster.arn
  version  = "1.36"

  vpc_config {
    subnet_ids = [
      aws_subnet.private["a"].id,
      aws_subnet.private["c"].id
    ]

    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.eks_public_access_cidrs
  }

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true
  }

  upgrade_policy {
    support_type = "STANDARD"
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster
  ]

  tags = {
    Name = "aegis-eks"
  }
}
