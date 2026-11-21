resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "aegis-workers"
  node_role_arn   = aws_iam_role.eks_node.arn

  subnet_ids = [
    aws_subnet.private["a"].id,
    aws_subnet.private["c"].id
  ]

  instance_types = ["m7i-flex.large"]
  capacity_type  = "ON_DEMAND"
  disk_size      = 20

  scaling_config {
    desired_size = 2
    min_size     = 1
    max_size     = 2
  }

  update_config {
    max_unavailable = 1
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_worker,
    aws_iam_role_policy_attachment.eks_ecr,
    aws_iam_role_policy_attachment.eks_cni
  ]

  tags = {
    Name = "aegis-workers"
  }
}
