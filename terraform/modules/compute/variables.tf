variable "environment" {
  type        = string
  description = "Target environment: dev, staging, prod"
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnets for ALB"
}

variable "private_app_subnet_ids" {
  type        = list(string)
  description = "Private app subnets for ECS tasks"
}

variable "alb_security_group_id" {
  type        = string
  description = "Security group for ALB"
}

variable "ecs_security_group_id" {
  type        = string
  description = "Security group for ECS"
}

variable "acm_certificate_arn" {
  type        = string
  default     = "arn:aws:acm:us-east-1:123456789012:certificate/placeholder"
  description = "ACM Certificate ARN for HTTPS"
}

variable "waf_acl_arn" {
  type        = string
  description = "WAFv2 WebACL ARN"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS CMK ARN for log group encryption"
}

variable "ecs_task_execution_role_arn" {
  type        = string
  description = "ECS Task Execution IAM Role ARN"
}

variable "ecs_task_role_arn" {
  type        = string
  description = "ECS Task Runtime IAM Role ARN"
}

variable "app_secrets_arn" {
  type        = string
  description = "Secrets Manager ARN"
}

variable "container_image" {
  type        = string
  default     = "123456789012.dkr.ecr.us-east-1.amazonaws.com/financial-copilot"
}

variable "image_tag" {
  type        = string
  default     = "latest"
}

variable "container_cpu" {
  type        = number
  default     = 2048 # 2 vCPU
}

variable "container_memory" {
  type        = number
  default     = 4096 # 4 GiB
}

variable "desired_count" {
  type        = number
  default     = 2
}

variable "min_count" {
  type        = number
  default     = 2
}

variable "max_count" {
  type        = number
  default     = 10
}

variable "enable_blue_green" {
  type        = bool
  default     = false
  description = "Enable CodeDeploy Blue/Green deployment controller"
}

variable "tags" {
  type        = map(string)
  default     = {}
}
