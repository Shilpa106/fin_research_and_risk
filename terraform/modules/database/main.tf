# -----------------------------------------------------------------------------
# AURORA POSTGRESQL SERVERLESS V2 (MULTI-AZ)
# -----------------------------------------------------------------------------

resource "random_password" "db_master" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_db_subnet_group" "aurora" {
  name        = "aurora-subnet-group-${var.environment}"
  subnet_ids  = var.database_subnet_ids
  description = "Multi-AZ Subnet group for Aurora PostgreSQL"

  tags = merge(var.tags, {
    Name = "aurora-subnet-group-${var.environment}"
  })
}

resource "aws_rds_cluster_parameter_group" "aurora_pg16" {
  name        = "aurora-pg16-params-${var.environment}"
  family      = "aurora-postgresql16"
  description = "Optimized parameters for Financial Copilot Aurora PostgreSQL"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements,pgcrypto"
  }

  parameter {
    name  = "track_io_timing"
    value = "1"
  }

  tags = var.tags
}

resource "aws_rds_cluster" "aurora" {
  cluster_identifier              = "financial-copilot-db-${var.environment}"
  engine                          = "aurora-postgresql"
  engine_version                  = "16.1"
  database_name                   = var.database_name
  master_username                 = var.master_username
  master_password                 = random_password.db_master.result
  db_subnet_group_name            = aws_db_subnet_group.aurora.name
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.aurora_pg16.name
  vpc_security_group_ids          = [var.db_security_group_id]

  storage_encrypted               = true
  kms_key_id                      = var.kms_key_arn

  backup_retention_period         = var.backup_retention_period
  preferred_backup_window         = "03:00-04:00"
  preferred_maintenance_window    = "sun:04:30-sun:05:30"
  copy_tags_to_snapshot           = true
  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = var.environment == "dev" ? true : false
  final_snapshot_identifier       = "financial-copilot-db-final-snapshot-${var.environment}"

  enabled_cloudwatch_logs_exports = ["postgresql"]

  serverlessv2_scaling_configuration {
    min_capacity = var.min_capacity
    max_capacity = var.max_capacity
  }

  tags = merge(var.tags, {
    Name = "aurora-postgresql-${var.environment}"
  })
}

# Multi-AZ Aurora Instances: Primary writer + Replica reader in different AZs
resource "aws_rds_cluster_instance" "instances" {
  count              = 2
  identifier         = "financial-copilot-db-${var.environment}-${count.index + 1}"
  cluster_identifier = aws_rds_cluster.aurora.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.aurora.engine
  engine_version     = aws_rds_cluster.aurora.engine_version
  auto_minor_version_upgrade = true

  db_subnet_group_name = aws_db_subnet_group.aurora.name
  monitoring_interval  = 60
  performance_insights_enabled = true
  performance_insights_kms_key_id = var.kms_key_arn

  tags = merge(var.tags, {
    Name = "aurora-instance-${var.environment}-${count.index + 1}"
    Role = count.index == 0 ? "writer" : "reader"
  })
}

# Store database credentials securely in AWS Secrets Manager
resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "copilot/${var.environment}/database/credentials"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.environment == "prod" ? 30 : 0

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    engine   = "postgresql"
    host     = aws_rds_cluster.aurora.endpoint
    reader_host = aws_rds_cluster.aurora.reader_endpoint
    port     = aws_rds_cluster.aurora.port
    username = var.master_username
    password = random_password.db_master.result
    database = var.database_name
    url      = "postgresql+asyncpg://${var.master_username}:${random_password.db_master.result}@${aws_rds_cluster.aurora.endpoint}:${aws_rds_cluster.aurora.port}/${var.database_name}"
  })
}

# -----------------------------------------------------------------------------
# ELASTICACHE REDIS REPLICATION GROUP (MULTI-AZ)
# -----------------------------------------------------------------------------

resource "random_password" "redis_auth_token" {
  length  = 32
  special = false
}

resource "aws_elasticache_subnet_group" "redis" {
  name        = "redis-subnet-group-${var.environment}"
  subnet_ids  = var.redis_subnet_ids
  description = "Multi-AZ Subnet group for ElastiCache Redis"

  tags = var.tags
}

resource "aws_elasticache_parameter_group" "redis7" {
  name        = "redis7-params-${var.environment}"
  family      = "redis7"
  description = "Parameter group for Redis 7.x caching and state"

  parameter {
    name  = "maxmemory-policy"
    value = "volatile-lru"
  }

  tags = var.tags
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id          = "copilot-redis-${var.environment}"
  description                   = "Multi-AZ Redis cluster for session cache and rate-limiting"
  node_type                     = var.redis_node_type
  num_cache_clusters            = var.redis_num_cache_clusters
  port                          = 6379
  parameter_group_name          = aws_elasticache_parameter_group.redis7.name
  subnet_group_name             = aws_elasticache_subnet_group.redis.name
  security_group_ids            = [var.redis_security_group_id]

  automatic_failover_enabled    = true
  multi_az_enabled              = true
  engine_version                = "7.1"
  auto_minor_version_upgrade    = true

  at_rest_encryption_enabled    = true
  kms_key_id                    = var.kms_key_arn
  transit_encryption_enabled    = true
  auth_token                    = random_password.redis_auth_token.result

  snapshot_retention_limit      = var.backup_retention_period > 0 ? 7 : 0
  snapshot_window               = "02:00-03:00"
  maintenance_window            = "sun:03:30-sun:04:30"

  tags = merge(var.tags, {
    Name = "redis-cluster-${var.environment}"
  })
}

# Store Redis auth token in AWS Secrets Manager
resource "aws_secretsmanager_secret" "redis_credentials" {
  name                    = "copilot/${var.environment}/redis/credentials"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.environment == "prod" ? 30 : 0

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "redis_credentials" {
  secret_id = aws_secretsmanager_secret.redis_credentials.id
  secret_string = jsonencode({
    host       = aws_elasticache_replication_group.redis.primary_endpoint_address
    reader_host = aws_elasticache_replication_group.redis.reader_endpoint_address
    port       = 6379
    auth_token = random_password.redis_auth_token.result
    url        = "rediss://:${random_password.redis_auth_token.result}@${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"
  })
}
