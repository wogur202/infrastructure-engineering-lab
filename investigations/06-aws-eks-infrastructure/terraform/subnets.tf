resource "aws_subnet" "public" {
  for_each = {
    a = { cidr = "10.20.1.0/24", az = "ap-northeast-2a" }
    c = { cidr = "10.20.2.0/24", az = "ap-northeast-2c" }
  }

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = true

  tags = {
    Name                     = "aegis-public-${each.key}"
    "kubernetes.io/role/elb" = "1"
  }
}

resource "aws_subnet" "private" {
  for_each = {
    a = { cidr = "10.20.11.0/24", az = "ap-northeast-2a" }
    c = { cidr = "10.20.12.0/24", az = "ap-northeast-2c" }
  }

  vpc_id            = aws_vpc.main.id
  cidr_block        = each.value.cidr
  availability_zone = each.value.az

  tags = {
    Name                              = "aegis-private-${each.key}"
    "kubernetes.io/role/internal-elb" = "1"
  }
}
