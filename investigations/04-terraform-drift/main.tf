
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region  = "ap-northeast-2"
  profile = "terraform-lab"
}

resource "aws_security_group" "drift_lab" {
  name        = "terraform-drift-lab"
  description = "Security group for Terraform drift experiment"

  ingress = []

  tags = {
    Name    = "terraform-drift-lab"
    Project = "portfolio-a"
  }
}
