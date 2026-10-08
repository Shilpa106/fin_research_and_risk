variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
}

variable "kms_key_arn" {
  type        = string
  description = "Customer Managed KMS Key ARN for S3 and SQS encryption"
}

variable "noncurrent_version_retention_days" {
  type        = number
  default     = 90
  description = "Number of days before non-current document versions are transitioned or deleted"
}

variable "message_retention_seconds" {
  type        = number
  default     = 1209600 # 14 days
  description = "SQS message retention period in seconds"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}
