variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS deployment region"
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Deployment environment name"
}

variable "vpc_cidr" {
  type        = string
  default     = "10.0.0.0/16"
  description = "Base VPC CIDR block"
}

variable "domain_name" {
  type        = string
  default     = "dev.finrisk.internal"
  description = "Domain name for dev environment"
}

variable "container_image" {
  type        = string
  default     = "123456789012.dkr.ecr.us-east-1.amazonaws.com/financial-copilot:dev-latest"
  description = "Container image tag for ECS task"
}

variable "tags" {
  type        = map(string)
  default = {
    Environment = "dev"
    Project     = "enterprise-financial-copilot"
    ManagedBy   = "Terraform"
  }
}
