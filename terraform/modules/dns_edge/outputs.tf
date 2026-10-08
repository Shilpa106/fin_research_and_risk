output "route53_zone_id" {
  description = "Route53 hosted zone ID"
  value       = aws_route53_zone.main.zone_id
}

output "route53_zone_name_servers" {
  description = "Name servers for the Route53 hosted zone"
  value       = aws_route53_zone.main.name_servers
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID"
  value       = aws_cloudfront_distribution.cdn.id
}

output "cloudfront_distribution_arn" {
  description = "CloudFront distribution ARN"
  value       = aws_cloudfront_distribution.cdn.arn
}

output "cloudfront_domain_name" {
  description = "CloudFront distribution domain name"
  value       = aws_cloudfront_distribution.cdn.domain_name
}

output "api_gateway_endpoint" {
  description = "HTTP API Gateway endpoint URL"
  value       = var.enable_api_gateway ? aws_apigatewayv2_stage.default[0].invoke_url : null
}
