output "domain_id" {
  description = "Unique identifier of the OpenSearch domain"
  value       = aws_opensearch_domain.cluster.domain_id
}

output "domain_arn" {
  description = "ARN of the OpenSearch domain"
  value       = aws_opensearch_domain.cluster.arn
}

output "domain_endpoint" {
  description = "Domain-specific endpoint used to submit index and search requests"
  value       = aws_opensearch_domain.cluster.endpoint
}

output "kibana_endpoint" {
  description = "Domain-specific endpoint for OpenSearch Dashboards"
  value       = aws_opensearch_domain.cluster.dashboard_endpoint
}
