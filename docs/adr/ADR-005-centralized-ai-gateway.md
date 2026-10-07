# ADR-005: Centralized AI Gateway Pattern

## Status
Accepted

## Context
At a scale of 500–1,000 peak AI requests/second, scattering raw LLM calls throughout application microservices leads to severe issues:
- Uncontrolled foundation model costs
- AWS Bedrock quota exhaustion
- Inconsistent guardrail enforcement
- Lack of centralized token auditing and per-tenant cost attribution
- Absence of unified resilience policies (circuit breakers, fallbacks, retries)

## Decision
All model invocations (Claude 3.5 Sonnet, Claude 3.5 Haiku, Titan Embeddings) must pass through a **Centralized AI Gateway** abstraction.

## Why This Architecture Was Selected
1. **Semantic & Exact Caching Layer**: The AI Gateway checks Redis semantic cache (cosine similarity $> 0.96$) before calling Bedrock. For common market queries ("Summarize Apple Q3 10-Q CAPEX"), caching absorbs 35–45% of peak load, protecting Bedrock quotas and reducing LLM operating costs.
2. **Resilience, Fallbacks & Circuit Breaking**: The gateway manages exponential backoff, rate limit handling (HTTP 429), circuit breakers when provider latency spikes, and automatic model degradation (fallback from Sonnet to Haiku or cached summaries).
3. **Enterprise Guardrail Pipeline**: Guarantees that prompt injection sanitization and AWS Bedrock Guardrails (PII redaction, toxic advice checks, regulatory disclaimers) are enforced centrally on 100% of LLM calls, without depending on individual application developers.
4. **Token Auditing & FinOps**: Every prompt and completion token is logged with tenant attribution for precise billing and department chargebacks.

## Alternatives Considered
- **Direct Boto3 Calls in Business Logic**: Leads to code duplication, scattered error handling, security blind spots, and no unified caching.
