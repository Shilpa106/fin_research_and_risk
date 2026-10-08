data "aws_region" "current" {}

# -----------------------------------------------------------------------------
# SNS TOPICS FOR ALERTS
# -----------------------------------------------------------------------------

resource "aws_sns_topic" "alerts_critical" {
  name              = "copilot-alerts-critical-${var.environment}"
  kms_master_key_id = var.kms_key_arn

  tags = merge(var.tags, {
    Severity = "CRITICAL"
  })
}

resource "aws_sns_topic" "alerts_warning" {
  name              = "copilot-alerts-warning-${var.environment}"
  kms_master_key_id = var.kms_key_arn

  tags = merge(var.tags, {
    Severity = "WARNING"
  })
}

# -----------------------------------------------------------------------------
# CLOUDWATCH ALARMS: COMPUTE & API
# -----------------------------------------------------------------------------

# ECS High CPU Alarm
resource "aws_cloudwatch_metric_alarm" "ecs_high_cpu" {
  alarm_name          = "copilot-${var.environment}-ecs-cpu-high"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Alarm when ECS service average CPU utilization exceeds 80% for 3 minutes"
  alarm_actions       = [aws_sns_topic.alerts_warning.arn]
  ok_actions          = [aws_sns_topic.alerts_warning.arn]

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  tags = var.tags
}

# ECS High Memory Alarm
resource "aws_cloudwatch_metric_alarm" "ecs_high_memory" {
  alarm_name          = "copilot-${var.environment}-ecs-memory-high"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 85
  alarm_description   = "Alarm when ECS service memory utilization exceeds 85% for 3 minutes"
  alarm_actions       = [aws_sns_topic.alerts_warning.arn]
  ok_actions          = [aws_sns_topic.alerts_warning.arn]

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  tags = var.tags
}

# ALB 5XX High Error Rate
resource "aws_cloudwatch_metric_alarm" "alb_high_5xx" {
  alarm_name          = "copilot-${var.environment}-alb-high-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "Critical: ALB target 5XX error count exceeds 10 per minute"
  alarm_actions       = [aws_sns_topic.alerts_critical.arn]
  ok_actions          = [aws_sns_topic.alerts_critical.arn]

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  tags = var.tags
}

# Target High Latency
resource "aws_cloudwatch_metric_alarm" "alb_high_latency" {
  alarm_name          = "copilot-${var.environment}-target-high-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p95"
  threshold           = 1.0 # 1.0 second p95
  alarm_description   = "Target p95 latency exceeds 1000ms"
  alarm_actions       = [aws_sns_topic.alerts_warning.arn]

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  tags = var.tags
}

# -----------------------------------------------------------------------------
# CLOUDWATCH ALARMS: QUEUES & DATABASES
# -----------------------------------------------------------------------------

# SQS Dead Letter Queue Not Empty (CRITICAL P1)
resource "aws_cloudwatch_metric_alarm" "sqs_dlq_messages" {
  alarm_name          = "copilot-${var.environment}-sqs-dlq-not-empty"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "CRITICAL: Messages detected in ingestion dead letter queue"
  alarm_actions       = [aws_sns_topic.alerts_critical.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.sqs_dlq_name
  }

  tags = var.tags
}

# SQS Ingestion Backlog High
resource "aws_cloudwatch_metric_alarm" "sqs_backlog_high" {
  alarm_name          = "copilot-${var.environment}-sqs-backlog-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Average"
  threshold           = 3000
  alarm_description   = "Ingestion queue depth backlog exceeds 3,000 items"
  alarm_actions       = [aws_sns_topic.alerts_warning.arn]

  dimensions = {
    QueueName = var.sqs_queue_name
  }

  tags = var.tags
}

# Aurora PostgreSQL Serverless Capacity / CPU High
resource "aws_cloudwatch_metric_alarm" "aurora_high_cpu" {
  alarm_name          = "copilot-${var.environment}-aurora-cpu-high"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 85
  alarm_description   = "Aurora PostgreSQL CPU utilization exceeds 85%"
  alarm_actions       = [aws_sns_topic.alerts_warning.arn]

  dimensions = {
    DBClusterIdentifier = var.aurora_cluster_id
  }

  tags = var.tags
}

# ElastiCache Redis High Evictions
resource "aws_cloudwatch_metric_alarm" "redis_evictions" {
  alarm_name          = "copilot-${var.environment}-redis-evictions"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Evictions"
  namespace           = "AWS/ElastiCache"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "ElastiCache Redis is evicting keys due to memory pressure"
  alarm_actions       = [aws_sns_topic.alerts_warning.arn]

  dimensions = {
    ReplicationGroupId = var.redis_replication_group_id
  }

  tags = var.tags
}

# OpenSearch Cluster Status RED (CRITICAL P1)
resource "aws_cloudwatch_metric_alarm" "opensearch_red" {
  alarm_name          = "copilot-${var.environment}-opensearch-status-red"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ClusterStatus.red"
  namespace           = "AWS/ES"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  alarm_description   = "CRITICAL: OpenSearch cluster health status is RED (primary shard unallocated)"
  alarm_actions       = [aws_sns_topic.alerts_critical.arn]

  dimensions = {
    DomainName = var.opensearch_domain_name
    ClientId   = data.aws_caller_identity.current.account_id
  }

  tags = var.tags
}

data "aws_caller_identity" "current" {}

# -----------------------------------------------------------------------------
# COMPREHENSIVE CLOUDWATCH SERVICE DASHBOARD
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "platform" {
  dashboard_name = "copilot-operations-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix, { stat = "Sum", period = 60 }],
            [".", "HTTPCode_Target_2XX_Count", ".", ".", { stat = "Sum", period = 60, color = "#2ca02c" }],
            [".", "HTTPCode_Target_4XX_Count", ".", ".", { stat = "Sum", period = 60, color = "#ff7f0e" }],
            [".", "HTTPCode_Target_5XX_Count", ".", ".", { stat = "Sum", period = 60, color = "#d62728" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "ALB Request Traffic & Status Codes"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, { stat = "p50", period = 60, label = "p50 Response Time" }],
            ["...", { stat = "p95", period = 60, label = "p95 Response Time" }],
            ["...", { stat = "p99", period = 60, label = "p99 Response Time" }]
          ]
          view   = "timeSeries"
          region = data.aws_region.current.name
          title  = "ALB Target Latency Percentiles (p50 / p95 / p99)"
          yAxis  = { left = { min = 0, label = "Seconds" } }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ServiceName", var.ecs_service_name, "ClusterName", var.ecs_cluster_name, { stat = "Average", period = 60, label = "ECS CPU %" }],
            [".", "MemoryUtilization", ".", ".", ".", ".", { stat = "Average", period = 60, label = "ECS Memory %" }]
          ]
          view   = "timeSeries"
          region = data.aws_region.current.name
          title  = "ECS Fargate Compute Utilization"
          yAxis  = { left = { min = 0, max = 100 } }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.sqs_queue_name, { stat = "Average", period = 60, label = "Ingestion Queue Depth" }],
            [".", "ApproximateNumberOfMessagesVisible", "QueueName", var.sqs_dlq_name, { stat = "Maximum", period = 60, label = "DLQ Message Count", color = "#d62728" }]
          ]
          view   = "timeSeries"
          region = data.aws_region.current.name
          title  = "SQS Queue Depth & Dead-Letter Backlog"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/RDS", "ServerlessDatabaseCapacity", "DBClusterIdentifier", var.aurora_cluster_id, { stat = "Average", period = 60, label = "Aurora ACUs" }],
            [".", "CPUUtilization", ".", ".", { stat = "Average", period = 60, label = "Aurora CPU %" }],
            [".", "DatabaseConnections", ".", ".", { stat = "Average", period = 60, label = "Active DB Connections" }]
          ]
          view   = "timeSeries"
          region = data.aws_region.current.name
          title  = "Aurora PostgreSQL Serverless v2 Scaling & Load"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ES", "SearchLatency", "DomainName", var.opensearch_domain_name, "ClientId", data.aws_caller_identity.current.account_id, { stat = "p95", period = 60, label = "OpenSearch p95 Search Latency" }],
            [".", "IndexingLatency", ".", ".", ".", ".", { stat = "p95", period = 60, label = "OpenSearch p95 Indexing Latency" }],
            [".", "CPUUtilization", ".", ".", ".", ".", { stat = "Average", period = 60, label = "OpenSearch CPU %" }]
          ]
          view   = "timeSeries"
          region = data.aws_region.current.name
          title  = "OpenSearch Performance & Latency"
        }
      }
    ]
  })
}
