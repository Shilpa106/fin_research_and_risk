output "vpc_id" {
  value = module.networking.vpc_id
}

output "alb_dns_name" {
  value = module.compute.alb_dns_name
}

output "cloudfront_domain_name" {
  value = module.dns_edge.cloudfront_domain_name
}

output "aurora_endpoint" {
  value = module.database.aurora_endpoint
}

output "aurora_reader_endpoint" {
  value = module.database.aurora_reader_endpoint
}

output "redis_primary_endpoint" {
  value = module.database.redis_primary_endpoint
}

output "opensearch_endpoint" {
  value = module.opensearch.domain_endpoint
}

output "documents_bucket" {
  value = module.storage_messaging.documents_bucket_name
}

output "ingestion_queue_url" {
  value = module.storage_messaging.ingestion_queue_id
}

output "dashboard_name" {
  value = module.monitoring.dashboard_name
}

output "critical_alarm_topic_arn" {
  value = module.monitoring.critical_alarm_topic_arn
}
