variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
}

variable "domain_name" {
  type        = string
  default     = "copilot.finrisk.internal"
  description = "Top-level domain name for Route53 hosted zone"
}

variable "alb_dns_name" {
  type        = string
  description = "DNS name of the origin ALB"
}

variable "alb_zone_id" {
  type        = string
  description = "Hosted zone ID of the origin ALB"
}

variable "cloudfront_waf_web_acl_arn" {
  type        = string
  default     = null
  description = "ARN of CloudFront AWS WAF WebACL (us-east-1)"
}

variable "price_class" {
  type        = string
  default     = "PriceClass_100"
  description = "CloudFront distribution price class"
}

variable "enable_api_gateway" {
  type        = bool
  default     = true
  description = "Whether to provision an API Gateway HTTP entrypoint in front of the ALB"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}
