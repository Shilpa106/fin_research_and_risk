output "alb_id" {
  description = "ID of the Application Load Balancer"
  value       = aws_lb.main.id
}

output "alb_arn" {
  description = "ARN of the Application Load Balancer"
  value       = aws_lb.main.arn
}

output "alb_arn_suffix" {
  description = "ARN suffix of the Application Load Balancer for CloudWatch metrics"
  value       = aws_lb.main.arn_suffix
}

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "Canonical hosted zone ID of the ALB"
  value       = aws_lb.main.zone_id
}

output "alb_listener_arn" {
  description = "ARN of the HTTPS listener"
  value       = aws_lb_listener.https.arn
}

output "target_group_blue_arn" {
  description = "ARN of the primary Blue target group"
  value       = aws_lb_target_group.blue.arn
}

output "target_group_blue_arn_suffix" {
  description = "ARN suffix of the Blue target group for CloudWatch metrics"
  value       = aws_lb_target_group.blue.arn_suffix
}

output "target_group_blue_name" {
  description = "Name of the Blue target group"
  value       = aws_lb_target_group.blue.name
}

output "target_group_green_arn" {
  description = "ARN of the Green target group"
  value       = aws_lb_target_group.green.arn
}

output "target_group_green_name" {
  description = "Name of the Green target group"
  value       = aws_lb_target_group.green.name
}

output "ecs_cluster_id" {
  description = "ID of the ECS cluster"
  value       = aws_ecs_cluster.main.id
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  value       = aws_ecs_cluster.main.arn
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_id" {
  description = "ID of the ECS service"
  value       = aws_ecs_service.api.id
}

output "ecs_service_name" {
  description = "Name of the ECS service"
  value       = aws_ecs_service.api.name
}
