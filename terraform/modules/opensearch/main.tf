data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# CloudWatch Log Groups for OpenSearch Slow Logs and Application Logs
resource "aws_cloudwatch_log_group" "opensearch_index_slow" {
  name              = "/aws/opensearch/copilot-${var.environment}/index-slow-logs"
  retention_in_days = var.environment == "prod" ? 30 : 7
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "opensearch_search_slow" {
  name              = "/aws/opensearch/copilot-${var.environment}/search-slow-logs"
  retention_in_days = var.environment == "prod" ? 30 : 7
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

resource "aws_cloudwatch_log_resource_policy" "opensearch_logging" {
  policy_name = "opensearch-log-policy-${var.environment}"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "es.amazonaws.com"
        }
        Action = [
          "logs:PutLogEvents",
          "logs:PutLogEventsBatch",
          "logs:CreateLogStream"
        ]
        Resource = "arn:aws:logs:*:*:log-group:/aws/opensearch/*:*"
      }
    ]
  })
}

# OpenSearch Service-Linked Role
resource "aws_iam_service_linked_role" "opensearch" {
  count            = var.environment == "dev" ? 0 : 0 # Assuming SLR is present or created globally
  aws_service_name = "opensearchservice.amazonaws.com"
}

# OpenSearch Cluster
resource "aws_opensearch_domain" "cluster" {
  domain_name    = "copilot-search-${var.environment}"
  engine_version = "OpenSearch_2.11"

  cluster_config {
    instance_type          = var.instance_type
    instance_count         = var.instance_count
    zone_awareness_enabled = var.zone_awareness_enabled

    dynamic "zone_awareness_config" {
      for_each = var.zone_awareness_enabled ? [1] : []
      content {
        availability_zone_count = var.availability_zone_count
      }
    }

    dedicated_master_enabled = var.dedicated_master_enabled
    dedicated_master_type    = var.dedicated_master_enabled ? var.dedicated_master_type : null
    dedicated_master_count   = var.dedicated_master_enabled ? var.dedicated_master_count : null

    warm_enabled = false
  }

  vpc_options {
    subnet_ids         = var.zone_awareness_enabled ? slice(var.subnet_ids, 0, var.availability_zone_count) : [var.subnet_ids[0]]
    security_group_ids = [var.security_group_id]
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.ebs_volume_size
    iops        = 3000
    throughput  = 125
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = var.kms_key_arn
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.opensearch_index_slow.arn
    log_type                 = "INDEX_SLOW_LOGS"
  }

  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.opensearch_search_slow.arn
    log_type                 = "SEARCH_SLOW_LOGS"
  }

  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = var.ecs_task_role_arn
        }
        Action   = "es:ESHttp*"
        Resource = "arn:aws:es:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:domain/copilot-search-${var.environment}/*"
      }
    ]
  })

  tags = merge(var.tags, {
    Name = "copilot-search-${var.environment}"
  })
}
