aws_region      = "us-east-1"
environment     = "staging"
vpc_cidr        = "10.1.0.0/16"
domain_name     = "staging.finrisk.internal"
container_image = "123456789012.dkr.ecr.us-east-1.amazonaws.com/financial-copilot:staging-rc"

tags = {
  Environment = "staging"
  Project     = "enterprise-financial-copilot"
  CostCenter  = "engineering-staging"
  ManagedBy   = "Terraform"
}
