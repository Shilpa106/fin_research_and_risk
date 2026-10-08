variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS deployment region"
}

variable "environment" {
  type        = string
  default     = "prod"
  description = "Deployment environment name"
}

variable "vpc_cidr" {
  type        = string
  default     = "10.2.0.0/16"
  description = "Base VPC CIDR block for production"
}

variable "domain_name" {
  type        = string
  default     = "copilot.finrisk.internal"
  description = "Production domain name"
}

variable "container_image" {
  type        = string
  default     = "123456789012.dkr.ecr.us-east-1.amazonaws.com/financial-copilot:v1.0.0"
  description = "Container image tag for production ECS task"
}

variable "alert_email" {
  type        = string
  default     = "sre-core-alerts@finrisk.internal"
  description = "Primary SRE alert notification email"
}

variable "tags" {
  type        = map(string)
  default = {
    Environment        = "prod"
    Project            = "enterprise-financial-copilot"
    Compliance         = "SOC2-Type-II"
    DataClassification = "Confidential-Financial"
    ManagedBy          = "Terraform"
  }
}
