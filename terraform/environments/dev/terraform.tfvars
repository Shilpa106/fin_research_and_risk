aws_region      = "us-east-1"
environment     = "dev"
vpc_cidr        = "10.0.0.0/16"
domain_name     = "dev.finrisk.internal"
container_image = "123456789012.dkr.ecr.us-east-1.amazonaws.com/financial-copilot:dev-latest"

tags = {
  Environment = "dev"
  Project     = "enterprise-financial-copilot"
  CostCenter  = "engineering-dev"
  ManagedBy   = "Terraform"
}
