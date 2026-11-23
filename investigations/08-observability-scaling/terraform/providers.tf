terraform {
  required_version = ">= 1.17.0, < 2.0.0"
  backend "local" {
    path = ".state/terraform.tfstate"
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.73.0"
    }
  }
}

provider "aws" {
  region              = "ap-northeast-2"
  profile             = var.aws_profile
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = {
      Project   = "project-aegis"
      Step      = "08"
      ManagedBy = "terraform"
      Scope     = "aegis-step08"
    }
  }
}

locals {
  name = "aegis-step08"
  azs  = { a = "ap-northeast-2a", c = "ap-northeast-2c" }
}
