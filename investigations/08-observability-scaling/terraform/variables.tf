variable "aws_profile" {
  type    = string
  default = "terraform-lab"
}

variable "expected_account_id" {
  type        = string
  description = "Required explicit account guard; do not commit account-specific tfvars."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Supply a 12-digit AWS account ID."
  }
}

variable "eks_public_access_cidrs" {
  type = list(string)
  validation {
    condition = length(var.eks_public_access_cidrs) > 0 && alltrue([
      for cidr in var.eks_public_access_cidrs :
      can(cidrnetmask(cidr)) && can(regex("/32$", cidr))
    ])
    error_message = "Use explicit public IPv4 /32 CIDRs for the administrator only."
  }
}

variable "lab_budget_usd" {
  type        = number
  default     = 5
  description = "Planning guard only. This does NOT create an AWS Budget or stop billing."
  validation {
    condition     = var.lab_budget_usd > 0 && var.lab_budget_usd <= 5
    error_message = "Review the design before raising the proposed USD 5 budget."
  }
}

variable "max_lab_hours" {
  type        = number
  default     = 6
  description = "Manual stop/export/cleanup deadline, not an automatic deletion timer."
  validation {
    condition     = var.max_lab_hours > 0 && var.max_lab_hours <= 6
    error_message = "Stop new experiments within 6h; reserve cleanup time separately."
  }
}
