output "kms_key_arn" {
  value       = aws_kms_key.main.arn
  description = "Customer Managed KMS Key ARN"
}

output "kms_key_id" {
  value       = aws_kms_key.main.key_id
  description = "Customer Managed KMS Key ID"
}

output "ecs_task_execution_role_arn" {
  value       = aws_iam_role.ecs_execution.arn
  description = "ECS Task Execution IAM Role ARN"
}

output "ecs_task_role_arn" {
  value       = aws_iam_role.ecs_task.arn
  description = "ECS Task Runtime IAM Role ARN"
}

output "waf_acl_arn" {
  value       = aws_wafv2_web_acl.main.arn
  description = "AWS WAFv2 WebACL ARN"
}

output "app_secrets_arn" {
  value       = aws_secretsmanager_secret.app_secrets.arn
  description = "Secrets Manager secret ARN"
}
