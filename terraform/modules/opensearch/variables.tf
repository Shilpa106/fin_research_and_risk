variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID where OpenSearch is deployed"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs across AZs for OpenSearch VPC endpoints"
}

variable "security_group_id" {
  type        = string
  description = "Security group ID for OpenSearch cluster"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Customer Managed Key ARN for at-rest encryption"
}

variable "instance_type" {
  type        = string
  default     = "r6g.large.search"
  description = "Instance type for data nodes"
}

variable "instance_count" {
  type        = number
  default     = 3
  description = "Number of data nodes in the cluster"
}

variable "dedicated_master_enabled" {
  type        = bool
  default     = true
  description = "Enable dedicated master nodes"
}

variable "dedicated_master_type" {
  type        = string
  default     = "c6g.large.search"
  description = "Instance type for dedicated master nodes"
}

variable "dedicated_master_count" {
  type        = number
  default     = 3
  description = "Number of dedicated master nodes"
}

variable "ebs_volume_size" {
  type        = number
  default     = 100
  description = "EBS volume size in GiB per node"
}

variable "zone_awareness_enabled" {
  type        = bool
  default     = true
  description = "Enable multi-AZ zone awareness"
}

variable "availability_zone_count" {
  type        = number
  default     = 3
  description = "Number of AZs for zone awareness (2 or 3)"
}

variable "ecs_task_role_arn" {
  type        = string
  description = "ARN of the ECS task role allowed to index and search OpenSearch"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}
