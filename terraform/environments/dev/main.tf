terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.30"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

# -----------------------------------------------------------------------------
# 1. NETWORKING (VPC, Subnets, NAT Gateway, Security Groups)
# -----------------------------------------------------------------------------
module "networking" {
  source = "../../modules/networking"

  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  enable_nat_gateway = true
  single_nat_gateway = true # Cost optimization for dev environment
  tags               = var.tags
}

# -----------------------------------------------------------------------------
# 2. STORAGE & MESSAGING (S3 Buckets, SQS Queues)
# -----------------------------------------------------------------------------
module "storage_messaging" {
  source = "../../modules/storage_messaging"

  environment                       = var.environment
  kms_key_arn                       = module.security.kms_key_arn
  noncurrent_version_retention_days = 30
  tags                              = var.tags
}

# -----------------------------------------------------------------------------
# 3. SECURITY & IAM (KMS, Roles, Policies, WAF)
# -----------------------------------------------------------------------------
module "security" {
  source = "../../modules/security"

  environment     = var.environment
  s3_bucket_arns  = [module.storage_messaging.documents_bucket_arn, "${module.storage_messaging.documents_bucket_arn}/*"]
  sqs_queue_arns  = [
    module.storage_messaging.ingestion_queue_arn,
    module.storage_messaging.ingestion_dlq_arn,
    module.storage_messaging.audit_queue_arn
  ]
  tags            = var.tags
}

# -----------------------------------------------------------------------------
# 4. DATABASE & CACHE (Aurora Serverless v2, ElastiCache Redis)
# -----------------------------------------------------------------------------
module "database" {
  source = "../../modules/database"

  environment             = var.environment
  vpc_id                  = module.networking.vpc_id
  database_subnet_ids     = module.networking.data_subnet_ids
  redis_subnet_ids        = module.networking.data_subnet_ids
  db_security_group_id    = module.networking.db_security_group_id
  redis_security_group_id = module.networking.redis_security_group_id
  kms_key_arn             = module.security.kms_key_arn

  min_capacity            = 0.5
  max_capacity            = 2.0
  backup_retention_period = 7
  deletion_protection     = false
  redis_node_type         = "cache.t4g.small"
  redis_num_cache_clusters = 2
  tags                    = var.tags
}

# -----------------------------------------------------------------------------
# 5. OPENSEARCH CLUSTER
# -----------------------------------------------------------------------------
module "opensearch" {
  source = "../../modules/opensearch"

  environment              = var.environment
  vpc_id                   = module.networking.vpc_id
  subnet_ids               = module.networking.data_subnet_ids
  security_group_id        = module.networking.opensearch_security_group_id
  kms_key_arn              = module.security.kms_key_arn
  instance_type            = "t3.small.search"
  instance_count           = 1
  dedicated_master_enabled = false
  zone_awareness_enabled   = false
  ebs_volume_size          = 20
  ecs_task_role_arn        = module.security.ecs_task_role_arn
  tags                     = var.tags
}

# -----------------------------------------------------------------------------
# 6. COMPUTE (ALB, ECS Fargate, Blue/Green Target Groups, Autoscaling)
# -----------------------------------------------------------------------------
module "compute" {
  source = "../../modules/compute"

  environment                    = var.environment
  vpc_id                         = module.networking.vpc_id
  public_subnet_ids              = module.networking.public_subnet_ids
  private_subnet_ids             = module.networking.app_subnet_ids
  alb_security_group_id          = module.networking.alb_security_group_id
  ecs_security_group_id          = module.networking.ecs_security_group_id
  waf_web_acl_arn                = module.security.waf_web_acl_arn
  kms_key_arn                    = module.security.kms_key_arn
  task_execution_role_arn        = module.security.ecs_task_execution_role_arn
  task_role_arn                  = module.security.ecs_task_role_arn
  database_credentials_secret_arn = module.database.db_credentials_secret_arn
  redis_credentials_secret_arn   = module.database.redis_credentials_secret_arn
  sqs_queue_name                 = module.storage_messaging.ingestion_queue_name
  container_image                = var.container_image
  cpu                            = 512
  memory                         = 1024
  min_capacity                   = 1
  max_capacity                   = 4
  tags                           = var.tags
}

# -----------------------------------------------------------------------------
# 7. DNS & EDGE (Route53, CloudFront, ACM, API Gateway)
# -----------------------------------------------------------------------------
module "dns_edge" {
  source = "../../modules/dns_edge"

  environment                = var.environment
  domain_name                = var.domain_name
  alb_dns_name               = module.compute.alb_dns_name
  alb_zone_id                = module.compute.alb_zone_id
  price_class                = "PriceClass_100"
  enable_api_gateway         = true
  tags                       = var.tags
}

# -----------------------------------------------------------------------------
# 8. MONITORING & OBSERVABILITY (CloudWatch Dashboards, Metric Alarms, SNS)
# -----------------------------------------------------------------------------
module "monitoring" {
  source = "../../modules/monitoring"

  environment                = var.environment
  ecs_cluster_name           = module.compute.ecs_cluster_name
  ecs_service_name           = module.compute.ecs_service_name
  alb_arn_suffix             = module.compute.alb_arn_suffix
  target_group_arn_suffix    = module.compute.target_group_blue_arn_suffix
  aurora_cluster_id          = module.database.aurora_cluster_id
  redis_replication_group_id = module.database.redis_replication_group_id
  sqs_queue_name             = module.storage_messaging.ingestion_queue_name
  sqs_dlq_name               = "copilot-ingestion-dlq-${var.environment}"
  opensearch_domain_name     = "copilot-search-${var.environment}"
  kms_key_arn                = module.security.kms_key_arn
  tags                       = var.tags
}
