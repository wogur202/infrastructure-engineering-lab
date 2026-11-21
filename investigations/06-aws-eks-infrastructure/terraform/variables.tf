variable "eks_public_access_cidrs" {
  description = "Allowed public IPv4 CIDRs for EKS API access"

  type = list(string)

  validation {
    condition = (
      length(var.eks_public_access_cidrs) > 0 &&
      alltrue([
        for cidr in var.eks_public_access_cidrs :
        can(cidrhost(cidr, 0)) && cidr != "0.0.0.0/0"
      ])
    )
    error_message = "Specify at least one restricted CIDR; 0.0.0.0/0 is not allowed."
  }
}
