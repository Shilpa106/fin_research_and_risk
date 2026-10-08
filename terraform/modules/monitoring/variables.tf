variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
}

variable "ecs_cluster_name" {
  type        = string
  description = "Name of the ECS cluster"
}

variable "ecs_service_name" {
  type        = string
  description = "Name of the ECS service"
}

variable "alb_arn_suffix" {
  type        = string
  description = "ARN suffix of the Application Load Balancer"
}

variable "target_group_arn_suffix" {
  type        = string
  description = "ARN suffix of the primary target group"
}

variable "aurora_cluster_id" {
  type        = string
  description = "Identifier of the Aurora PostgreSQL cluster"
}

variable "redis_replication_group_id" {
  type        = string
  description = "Identifier of the ElastiCache Redis replication group"
}

variable "sqs_queue_name" {
  type        = string
  description = "Name of the ingestion SQS queue"
}

variable "sqs_dlq_name" {
  type        = string
  description = "Name of the ingestion dead-letter SQS queue"
}

variable "opensearch_domain_name" {
  type        = string
  description = "Name of the OpenSearch domain"
}

variable "alert_email" {
  type        = string
  default     = "sre-alerts@finrisk.internal"
  description = "Email address for CloudWatch alarm notifications"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS Customer Managed Key ARN for SNS topic encryption"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}
