# Pins observed via DescribeAddonVersions for Kubernetes 1.36, 2026-11-23 KST.
# Metrics Server is installed ONLY by the separate pinned Helm chart.
resource "aws_eks_addon" "network" {
  for_each = {
    vpc-cni    = "v1.22.4-eksbuild.14"
    kube-proxy = "v1.36.0-eksbuild.65"
  }
  cluster_name  = aws_eks_cluster.lab.name
  addon_name    = each.key
  addon_version = each.value
}

resource "aws_eks_addon" "dns" {
  cluster_name  = aws_eks_cluster.lab.name
  addon_name    = "coredns"
  addon_version = "v1.14.7-eksbuild.35"
  depends_on    = [aws_eks_node_group.lab]
}
