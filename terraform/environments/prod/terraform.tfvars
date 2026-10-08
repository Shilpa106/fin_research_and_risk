aws_region      = "us-east-1"
environment     = "prod"
vpc_cidr        = "10.2.0.0/16"
domain_name     = "copilot.finrisk.internal"
container_image = "123456789012.dkr.ecr.us-east-1.amazonaws.com/financial-copilot:v1.0.0"
alert_email     = "sre-core-alerts@finrisk.internal"

tags = {
  Environment        = "prod"
  Project            = "enterprise-financial-copilot"
  Compliance         = "SOC2-Type-II"
  DataClassification = "Confidential-Financial"
  CostCenter         = "enterprise-core"
  ManagedBy          = "Terraform"
}
