variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS deployment region"
}

variable "environment" {
  type        = string
  default     = "staging"
  description = "Deployment environment name"
}

variable "vpc_cidr" {
  type        = string
  default     = "10.1.0.0/16"
  description = "Base VPC CIDR block"
}

variable "domain_name" {
  type        = string
  default     = "staging.finrisk.internal"
  description = "Domain name for staging environment"
}

variable "container_image" {
  type        = string
  default     = "123456789012.dkr.ecr.us-east-1.amazonaws.com/financial-copilot:staging-rc"
  description = "Container image tag for ECS task"
}

variable "tags" {
  type        = map(string)
  default = {
    Environment = "staging"
    Project     = "enterprise-financial-copilot"
    ManagedBy   = "Terraform"
  }
}
