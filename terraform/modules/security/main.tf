terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ==============================================================================
# KMS Customer Managed Key (CMK) with Automatic Key Rotation
# ==============================================================================

resource "aws_kms_key" "main" {
  description             = "CMK for ${var.environment} Financial Research Copilot encryption at rest"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EnableRootPermissions"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.aws_account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowCloudWatchLogs"
        Effect = "Allow"
        Principal = {
          Service = "logs.${var.aws_region}.amazonaws.com"
        }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:Describe*"
        ]
        Resource = "*"
      }
    ]
  })

  tags = merge(var.tags, {
    Name = "${var.environment}-cmk-key"
  })
}

resource "aws_kms_alias" "main" {
  name          = "alias/${var.environment}-financial-copilot"
  target_key_id = aws_kms_key.main.key_id
}

# ==============================================================================
# Least-Privilege IAM Roles
# ==============================================================================

# 1. ECS Task Execution Role (ECR pull, CloudWatch logs, SecretsManager decrypt)
resource "aws_iam_role" "ecs_execution" {
  name = "${var.environment}-ecs-task-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution_standard" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_policy" "ecs_execution_secrets" {
  name        = "${var.environment}-ecs-execution-secrets-policy"
  description = "Allows ECS agent to read SecretsManager and decrypt with KMS"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          aws_secretsmanager_secret.app_secrets.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = [
          aws_kms_key.main.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = aws_iam_policy.ecs_execution_secrets.arn
}

# 2. ECS Task Role (Runtime permissions: Bedrock, S3, SQS, OpenSearch, CloudWatch)
resource "aws_iam_role" "ecs_task" {
  name = "${var.environment}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_policy" "ecs_task_runtime" {
  name        = "${var.environment}-ecs-task-runtime-policy"
  description = "Scoped runtime permissions for Bedrock models, S3 storage, SQS messaging, and CloudWatch metrics"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Bedrock foundation models and guardrails
      {
        Sid    = "BedrockModelInvocation"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:ApplyGuardrail"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0",
          "arn:aws:bedrock:${var.aws_region}:${var.aws_account_id}:guardrail/*"
        ]
      },
      # CloudWatch Metrics PutMetricData
      {
        Sid    = "CloudWatchMetricsPut"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "EnterpriseFinCopilot"
          }
        }
      },
      # S3 Document & Snapshot Access
      {
        Sid    = "S3DocumentAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Resource = [
          "arn:aws:s3:::${var.environment}-financial-documents-${var.aws_account_id}",
          "arn:aws:s3:::${var.environment}-financial-documents-${var.aws_account_id}/*"
        ]
      },
      # SQS Queue Messaging
      {
        Sid    = "SQSMessagingAccess"
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = [
          "arn:aws:sqs:${var.aws_region}:${var.aws_account_id}:${var.environment}-document-ingestion-queue",
          "arn:aws:sqs:${var.aws_region}:${var.aws_account_id}:${var.environment}-audit-log-queue.fifo"
        ]
      },
      # KMS Decrypt/GenerateDataKey for application runtime
      {
        Sid    = "KMSEncryptionRuntime"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey*"
        ]
        Resource = [
          aws_kms_key.main.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_runtime" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ecs_task_runtime.arn
}

# ==============================================================================
# AWS Secrets Manager
# ==============================================================================

resource "aws_secretsmanager_secret" "app_secrets" {
  name                    = "${var.environment}/financial-copilot/credentials"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 7

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "app_secrets" {
  secret_id = aws_secretsmanager_secret.app_secrets.id
  secret_string = jsonencode({
    jwt_secret_key = "prod-managed-jwt-secret-key-32-chars-minimum"
    db_password    = "aurora-super-secure-generated-db-password-123!"
    redis_auth     = "redis-secure-token-cluster-auth-987"
  })
}

# ==============================================================================
# AWS WAFv2 WebACL (OWASP Top 10 & 10K RPS Rate Limiting)
# ==============================================================================

resource "aws_wafv2_web_acl" "main" {
  name        = "${var.environment}-financial-copilot-waf"
  description = "Enterprise WAF defending against SQLi, XSS, bots, and brute force volumetric attacks"
  scope       = var.waf_scope # "REGIONAL" for ALB, "CLOUDFRONT" for CloudFront

  default_action {
    allow {}
  }

  # Rule 1: IP Rate Limiting (Protects 10K RPS burst threshold)
  rule {
    name     = "RateLimitPerIP"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 10000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitPerIP"
      sampled_requests_enabled   = true
    }
  }

  # Rule 2: AWS Managed Common Rule Set (OWASP Top 10)
  rule {
    name     = "AWSManagedCommonRules"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedCommonRules"
      sampled_requests_enabled   = true
    }
  }

  # Rule 3: Known Bad Inputs
  rule {
    name     = "AWSManagedKnownBadInputs"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedKnownBadInputs"
      sampled_requests_enabled   = true
    }
  }

  # Rule 4: SQL Injection Protections
  rule {
    name     = "AWSManagedSQLi"
    priority = 4

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesSQLiRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedSQLi"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.environment}-financial-copilot-waf"
    sampled_requests_enabled   = true
  }

  tags = var.tags
}
