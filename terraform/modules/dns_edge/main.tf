# -----------------------------------------------------------------------------
# ROUTE53 HOSTED ZONE & DNS RECORDS
# -----------------------------------------------------------------------------

resource "aws_route53_zone" "main" {
  name          = var.domain_name
  comment       = "Hosted zone for Financial Copilot ${var.environment}"
  force_destroy = var.environment == "dev" ? true : false

  tags = var.tags
}

# -----------------------------------------------------------------------------
# ACM TLS CERTIFICATE
# -----------------------------------------------------------------------------

resource "aws_acm_certificate" "cert" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  subject_alternative_names = [
    "*.${var.domain_name}"
  ]

  lifecycle {
    create_before_destroy = true
  }

  tags = merge(var.tags, {
    Name = "cert-${var.environment}.${var.domain_name}"
  })
}

# -----------------------------------------------------------------------------
# API GATEWAY (HTTP API EDGE)
# -----------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "http_api" {
  count         = var.enable_api_gateway ? 1 : 0
  name          = "copilot-http-api-${var.environment}"
  protocol_type = "HTTP"
  description   = "API Gateway HTTP edge proxying requests to private ALB"

  cors_configuration {
    allow_origins = ["https://${var.domain_name}"]
    allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers = ["Content-Type", "Authorization", "X-Request-ID", "X-Tenant-ID"]
    max_age       = 3600
  }

  tags = var.tags
}

resource "aws_apigatewayv2_stage" "default" {
  count       = var.enable_api_gateway ? 1 : 0
  api_id      = aws_apigatewayv2_api.http_api[0].id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 5000
    throttling_rate_limit  = 10000
  }

  tags = var.tags
}

# -----------------------------------------------------------------------------
# CLOUDFRONT DISTRIBUTION
# -----------------------------------------------------------------------------

resource "random_password" "origin_verify_header" {
  length  = 32
  special = false
}

resource "aws_cloudfront_distribution" "cdn" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "CloudFront edge CDN for Financial Copilot (${var.environment})"
  price_class         = var.price_class
  web_acl_id          = var.cloudfront_waf_web_acl_arn

  aliases = [var.domain_name]

  origin {
    domain_name = var.alb_dns_name
    origin_id   = "ALB-${var.environment}"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify_header.result
    }
  }

  # Default cache behavior for API endpoints (no caching, full passthrough)
  default_cache_behavior {
    allowed_methods  = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "ALB-${var.environment}"

    forwarded_values {
      query_string = true
      headers      = ["*"]

      cookies {
        forward = "all"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 0
    max_ttl                = 0
    compress               = true
  }

  # Caching behavior for static assets / web docs
  ordered_cache_behavior {
    path_pattern     = "/static/*"
    allowed_methods  = ["GET", "HEAD", "OPTIONS"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "ALB-${var.environment}"

    forwarded_values {
      query_string = false
      headers      = ["Origin"]

      cookies {
        forward = "none"
      }
    }

    min_ttl                = 0
    default_ttl            = 86400
    max_ttl                = 604800
    compress               = true
    viewer_protocol_policy = "redirect-to-https"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate.cert.arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = merge(var.tags, {
    Name = "copilot-cdn-${var.environment}"
  })
}

# Route53 Alias Record pointing apex domain to CloudFront Distribution
resource "aws_route53_record" "apex" {
  zone_id = aws_route53_zone.main.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.cdn.domain_name
    zone_id                = aws_cloudfront_distribution.cdn.hosted_zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "apex_ipv6" {
  zone_id = aws_route53_zone.main.zone_id
  name    = var.domain_name
  type    = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.cdn.domain_name
    zone_id                = aws_cloudfront_distribution.cdn.hosted_zone_id
    evaluate_target_health = true
  }
}
