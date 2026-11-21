resource "aws_ecr_repository" "api" {
  name                 = "aegis-api"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "aegis-api"
  }
}
