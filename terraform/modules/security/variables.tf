variable "environment" {
  type        = string
  description = "Target deployment environment: dev, staging, prod"
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region"
}

variable "aws_account_id" {
  type        = string
  description = "AWS Account ID for ARN scoping"
  default     = "123456789012"
}

variable "waf_scope" {
  type        = string
  default     = "REGIONAL"
  description = "Scope for WAFv2: REGIONAL (ALB) or CLOUDFRONT"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}
