output "documents_bucket_name" {
  description = "Name of the S3 documents bucket"
  value       = aws_s3_bucket.documents.id
}

output "documents_bucket_arn" {
  description = "ARN of the S3 documents bucket"
  value       = aws_s3_bucket.documents.arn
}

output "ingestion_queue_id" {
  description = "URL of the ingestion SQS queue"
  value       = aws_sqs_queue.ingestion.id
}

output "ingestion_queue_arn" {
  description = "ARN of the ingestion SQS queue"
  value       = aws_sqs_queue.ingestion.arn
}

output "ingestion_queue_name" {
  description = "Name of the ingestion SQS queue"
  value       = aws_sqs_queue.ingestion.name
}

output "ingestion_dlq_arn" {
  description = "ARN of the ingestion dead-letter queue"
  value       = aws_sqs_queue.ingestion_dlq.arn
}

output "audit_queue_id" {
  description = "URL of the audit FIFO SQS queue"
  value       = aws_sqs_queue.audit.id
}

output "audit_queue_arn" {
  description = "ARN of the audit FIFO SQS queue"
  value       = aws_sqs_queue.audit.arn
}

output "audit_queue_name" {
  description = "Name of the audit FIFO SQS queue"
  value       = aws_sqs_queue.audit.name
}
