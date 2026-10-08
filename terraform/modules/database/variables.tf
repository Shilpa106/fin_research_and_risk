variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID where database resources reside"
}

variable "database_subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for Aurora DB Subnet Group across multiple AZs"
}

variable "redis_subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for ElastiCache Redis Subnet Group across multiple AZs"
}

variable "db_security_group_id" {
  type        = string
  description = "Security group ID for Aurora PostgreSQL"
}

variable "redis_security_group_id" {
  type        = string
  description = "Security group ID for ElastiCache Redis"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Customer Managed Key ARN for database and cache encryption"
}

variable "database_name" {
  type        = string
  default     = "financial_copilot"
  description = "Name of the initial PostgreSQL database"
}

variable "master_username" {
  type        = string
  default     = "copilot_admin"
  description = "Master username for Aurora PostgreSQL"
}

variable "min_capacity" {
  type        = number
  default     = 0.5
  description = "Minimum Aurora Serverless v2 capacity in ACUs"
}

variable "max_capacity" {
  type        = number
  default     = 16.0
  description = "Maximum Aurora Serverless v2 capacity in ACUs"
}

variable "backup_retention_period" {
  type        = number
  default     = 30
  description = "Backup retention window in days"
}

variable "deletion_protection" {
  type        = bool
  default     = true
  description = "Enforce deletion protection on Aurora PostgreSQL cluster"
}

variable "redis_node_type" {
  type        = string
  default     = "cache.t4g.medium"
  description = "Instance type for ElastiCache Redis nodes"
}

variable "redis_num_cache_clusters" {
  type        = number
  default     = 2
  description = "Number of cache clusters for Redis replication group (>=2 for Multi-AZ)"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}
