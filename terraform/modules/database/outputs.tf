output "aurora_cluster_id" {
  description = "Aurora Cluster identifier"
  value       = aws_rds_cluster.aurora.id
}

output "aurora_cluster_arn" {
  description = "Aurora Cluster ARN"
  value       = aws_rds_cluster.aurora.arn
}

output "aurora_endpoint" {
  description = "Aurora writer endpoint"
  value       = aws_rds_cluster.aurora.endpoint
}

output "aurora_reader_endpoint" {
  description = "Aurora read-only endpoint"
  value       = aws_rds_cluster.aurora.reader_endpoint
}

output "aurora_port" {
  description = "Aurora database port"
  value       = aws_rds_cluster.aurora.port
}

output "db_credentials_secret_arn" {
  description = "Secrets Manager ARN containing PostgreSQL connection strings and credentials"
  value       = aws_secretsmanager_secret.db_credentials.arn
}

output "redis_replication_group_id" {
  description = "ElastiCache Redis replication group ID"
  value       = aws_elasticache_replication_group.redis.id
}

output "redis_primary_endpoint" {
  description = "ElastiCache Redis primary endpoint address"
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "redis_reader_endpoint" {
  description = "ElastiCache Redis reader endpoint address"
  value       = aws_elasticache_replication_group.redis.reader_endpoint_address
}

output "redis_credentials_secret_arn" {
  description = "Secrets Manager ARN containing Redis auth token and connection URI"
  value       = aws_secretsmanager_secret.redis_credentials.arn
}
