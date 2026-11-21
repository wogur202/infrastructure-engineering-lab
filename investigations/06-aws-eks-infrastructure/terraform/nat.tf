resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "aegis-nat-eip"
  }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public["a"].id

  depends_on = [aws_internet_gateway.main]

  tags = {
    Name = "aegis-nat"
  }
}
