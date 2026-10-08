variable "environment" {
  type        = string
  description = "Target environment: dev, staging, prod"
}

variable "vpc_cidr" {
  type        = string
  default     = "10.0.0.0/16"
  description = "CIDR block for the VPC"
}

variable "availability_zones" {
  type        = list(string)
  description = "List of Availability Zones to deploy into"
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "single_nat_gateway" {
  type        = bool
  default     = false
  description = "If true, provision only 1 NAT Gateway for cost optimization (dev)"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Common resource tags"
}
