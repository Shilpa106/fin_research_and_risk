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
# Application Load Balancer (ALB) with Blue / Green Target Groups
# ==============================================================================

resource "aws_lb" "main" {
  name               = "${var.environment}-copilot-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_security_group_id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = var.environment == "prod" ? true : false
  drop_invalid_header_fields = true

  tags = merge(var.tags, {
    Name = "${var.environment}-copilot-alb"
  })
}

# Blue Target Group (Active / Primary)
resource "aws_lb_target_group" "blue" {
  name                 = "${var.environment}-tg-blue"
  port                 = 8000
  protocol             = "HTTP"
  vpc_id               = var.vpc_id
  target_type          = "ip"
  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = "/health/live"
    port                = "8000"
    protocol            = "HTTP"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  tags = merge(var.tags, {
    Name = "${var.environment}-tg-blue"
  })
}

# Green Target Group (Standby / Replacement for Blue/Green Deployments)
resource "aws_lb_target_group" "green" {
  name                 = "${var.environment}-tg-green"
  port                 = 8000
  protocol             = "HTTP"
  vpc_id               = var.vpc_id
  target_type          = "ip"
  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = "/health/live"
    port                = "8000"
    protocol            = "HTTP"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  tags = merge(var.tags, {
    Name = "${var.environment}-tg-green"
  })
}

# HTTPS Ingress Listener
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.blue.arn
  }
}

# HTTP to HTTPS Redirect Listener
resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# Associate Regional WAF with ALB
resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = aws_lb.main.arn
  web_acl_arn  = var.waf_acl_arn
}

# ==============================================================================
# ECS Fargate Cluster & Service
# ==============================================================================

resource "aws_ecs_cluster" "main" {
  name = "${var.environment}-financial-copilot-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.environment}-financial-copilot"
  retention_in_days = var.environment == "prod" ? 365 : 30
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

resource "aws_ecs_task_definition" "app" {
  family                   = "${var.environment}-financial-copilot"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.container_cpu
  memory                   = var.container_memory
  execution_role_arn       = var.ecs_task_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${var.container_image}:${var.image_tag}"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "LOG_LEVEL", value = var.environment == "prod" ? "INFO" : "DEBUG" },
        { name = "PROMETHEUS_METRICS_ENABLED", value = "true" },
        { name = "OTEL_ENABLED", value = "true" },
        { name = "AWS_REGION", value = var.aws_region }
      ]
      secrets = [
        {
          name      = "JWT_SECRET_KEY"
          valueFrom = "${var.app_secrets_arn}:jwt_secret_key::"
        },
        {
          name      = "DATABASE_PASSWORD"
          valueFrom = "${var.app_secrets_arn}:db_password::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "app"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "app" {
  name                               = "${var.environment}-copilot-service"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.app.arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  health_check_grace_period_seconds  = 60
  enable_execute_command             = true

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.blue.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_controller {
    type = var.enable_blue_green ? "CODE_DEPLOY" : "ECS"
  }

  lifecycle {
    ignore_changes = [
      task_definition,
      load_balancer
    ]
  }

  tags = var.tags
}

# ==============================================================================
# Multi-Dimensional Autoscaling Policies
# ==============================================================================

resource "aws_appautoscaling_target" "ecs" {
  max_capacity       = var.max_count
  min_capacity       = var.min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.app.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# 1. CPU Target Tracking Autoscaling (Target 60%)
resource "aws_appautoscaling_policy" "cpu" {
  name               = "${var.environment}-cpu-target-tracking"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 60.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# 2. Memory Target Tracking Autoscaling (Target 75%)
resource "aws_appautoscaling_policy" "memory" {
  name               = "${var.environment}-memory-target-tracking"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value       = 75.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# 3. ALB Request Count Per Target (Target 1,000 requests/target)
resource "aws_appautoscaling_policy" "request_count" {
  name               = "${var.environment}-request-count-tracking"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.main.arn_suffix}/${aws_lb_target_group.blue.arn_suffix}"
    }
    target_value       = 1000.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 30
  }
}

# 4. Latency-Based Step Scaling Policy (Scale out when ALB TargetResponseTime > 0.5s)
resource "aws_appautoscaling_policy" "latency_scale_out" {
  name               = "${var.environment}-latency-scale-out"
  policy_type        = "StepScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 60
    metric_aggregation_type = "Average"

    step_adjustment {
      metric_interval_lower_bound = 0
      scaling_adjustment          = 4
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_high_latency" {
  alarm_name          = "${var.environment}-alb-high-latency-alarm"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Average"
  threshold           = 0.50 # 500ms
  alarm_actions       = [aws_appautoscaling_policy.latency_scale_out.arn]

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.blue.arn_suffix
  }
}

# 5. Queue Depth Scaling (SQS ApproximateNumberOfMessagesVisible)
resource "aws_appautoscaling_policy" "queue_depth_scale_out" {
  name               = "${var.environment}-sqs-queue-depth-scale-out"
  policy_type        = "StepScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 60
    metric_aggregation_type = "Average"

    step_adjustment {
      metric_interval_lower_bound = 0
      scaling_adjustment          = 2
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "sqs_high_queue_depth" {
  alarm_name          = "${var.environment}-sqs-high-queue-depth-alarm"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Average"
  threshold           = 500
  alarm_actions       = [aws_appautoscaling_policy.queue_depth_scale_out.arn]

  dimensions = {
    QueueName = "${var.environment}-document-ingestion-queue"
  }
}
