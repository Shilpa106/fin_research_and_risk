data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# -----------------------------------------------------------------------------
# S3 DOCUMENT & FINANCIAL ARTIFACT REPOSITORY
# -----------------------------------------------------------------------------

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "documents" {
  bucket        = "copilot-financial-docs-${var.environment}-${random_id.bucket_suffix.hex}"
  force_destroy = var.environment == "dev" ? true : false

  tags = merge(var.tags, {
    Name        = "copilot-financial-docs-${var.environment}"
    Description = "Storage for ingested 10-K, 10-Q, earnings transcripts and research reports"
  })
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = var.kms_key_arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    id     = "archive-noncurrent-versions"
    status = "Enabled"

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_transition {
      noncurrent_days = 60
      storage_class   = "GLACIER"
    }

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_retention_days
    }
  }

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_policy" "enforce_tls" {
  bucket = aws_s3_bucket.documents.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnforceTLSRequestsOnly"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.documents.arn,
          "${aws_s3_bucket.documents.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# SQS INGESTION QUEUES & DEAD LETTER QUEUES
# -----------------------------------------------------------------------------

# Ingestion DLQ
resource "aws_sqs_queue" "ingestion_dlq" {
  name                      = "copilot-ingestion-dlq-${var.environment}"
  message_retention_seconds = var.message_retention_seconds
  kms_master_key_id         = var.kms_key_arn

  tags = merge(var.tags, {
    Name = "copilot-ingestion-dlq-${var.environment}"
  })
}

# Ingestion Primary Queue
resource "aws_sqs_queue" "ingestion" {
  name                       = "copilot-ingestion-queue-${var.environment}"
  visibility_timeout_seconds = 300 # 5 minutes for document chunking/indexing
  message_retention_seconds  = var.message_retention_seconds
  kms_master_key_id          = var.kms_key_arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingestion_dlq.arn
    maxReceiveCount     = 3
  })

  tags = merge(var.tags, {
    Name = "copilot-ingestion-queue-${var.environment}"
  })
}

# Audit Log FIFO DLQ
resource "aws_sqs_queue" "audit_dlq" {
  name                        = "copilot-audit-dlq-${var.environment}.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = var.message_retention_seconds
  kms_master_key_id           = var.kms_key_arn

  tags = merge(var.tags, {
    Name = "copilot-audit-dlq-${var.environment}"
  })
}

# Audit Log FIFO Queue
resource "aws_sqs_queue" "audit" {
  name                        = "copilot-audit-queue-${var.environment}.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 60
  message_retention_seconds   = var.message_retention_seconds
  kms_master_key_id           = var.kms_key_arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.audit_dlq.arn
    maxReceiveCount     = 5
  })

  tags = merge(var.tags, {
    Name = "copilot-audit-queue-${var.environment}"
  })
}
