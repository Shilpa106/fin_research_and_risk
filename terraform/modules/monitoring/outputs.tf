output "critical_alarm_topic_arn" {
  description = "ARN of the P1 Critical SNS alert topic"
  value       = aws_sns_topic.alerts_critical.arn
}

output "warning_alarm_topic_arn" {
  description = "ARN of the P2 Warning SNS alert topic"
  value       = aws_sns_topic.alerts_warning.arn
}

output "dashboard_name" {
  description = "Name of the operational CloudWatch dashboard"
  value       = aws_cloudwatch_dashboard.platform.dashboard_name
}
