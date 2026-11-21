terraform {
  required_version = ">= 1.17.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
  }
}

provider "aws" {
  region  = "ap-northeast-2"
  profile = "terraform-lab"

  default_tags {
    tags = {
      Project   = "project-aegis"
      ManagedBy = "terraform"
      Step      = "06"
    }
  }
}
