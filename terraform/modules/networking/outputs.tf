output "vpc_id" {
  value       = aws_vpc.main.id
  description = "The ID of the VPC"
}

output "public_subnet_ids" {
  value       = aws_subnet.public[*].id
  description = "List of public subnet IDs"
}

output "private_app_subnet_ids" {
  value       = aws_subnet.private_app[*].id
  description = "List of private application subnet IDs"
}

output "private_data_subnet_ids" {
  value       = aws_subnet.private_data[*].id
  description = "List of private database/data subnet IDs"
}

output "alb_security_group_id" {
  value       = aws_security_group.alb.id
  description = "ALB security group ID"
}

output "ecs_security_group_id" {
  value       = aws_security_group.ecs.id
  description = "ECS security group ID"
}

output "db_security_group_id" {
  value       = aws_security_group.db.id
  description = "Aurora database security group ID"
}

output "redis_security_group_id" {
  value       = aws_security_group.redis.id
  description = "ElastiCache security group ID"
}

output "opensearch_security_group_id" {
  value       = aws_security_group.opensearch.id
  description = "OpenSearch security group ID"
}
