# ADR-006: AWS Bedrock Foundation Models & Centralized AI Gateway

## Status
Accepted

## Context
At 500–1,000 peak AI requests/second, the platform requires institutional-grade foundation models for financial reasoning, dense text embeddings, and automated regulatory compliance guardrails. The architecture strictly mandates that all LLM calls route through a Centralized AI Gateway rather than raw API calls scattered across application code.

---

## Technical Evaluation (The 9 Architectural Dimensions)

### 1. Why this technology?
AWS Bedrock provides a fully managed, enterprise-secure API offering industry-leading models:
- **Anthropic Claude 3.5 Sonnet v2**: Unmatched reasoning accuracy on complex financial tables, SEC footnotes, and multi-step synthesis.
- **Anthropic Claude 3.5 Haiku**: Ultra-fast latency (~250ms TTFT) and low cost for query routing, entity extraction, and triage.
- **Amazon Titan Text Embeddings v2**: High-performance 1536-dimensional dense vector embeddings with normalized unit vectors for cosine search.
- **Bedrock Guardrails**: Native PII redaction, prompt injection filtering, and automated financial advice compliance policies.
Data processed by AWS Bedrock is never used to train base foundation models and stays within the customer's AWS VPC security perimeter.

### 2. What alternatives were considered?
- **Direct OpenAI API (GPT-4o)**
- **Self-Hosted Open Source Models (Llama 3.3 70B on GPU EC2 clusters)**
- **Azure OpenAI Service**
- **Scattering raw boto3 Bedrock calls throughout application code**

### 3. Why were they rejected?
- **Direct OpenAI API**: Data egresses AWS VPC boundaries into third-party cloud infrastructure, raising significant institutional compliance, latency, and data sovereignty concerns for global banks.
- **Self-Hosted Llama Models on GPU Clusters**: Hosting dozens of `p4d.24xlarge` GPU instances (8x A100/H100) costs $30,000+ per month in idle compute alone, requires dedicated MLOps infrastructure teams for model serving, and lags Claude 3.5 Sonnet on complex financial reasoning benchmarks.
- **Scattering raw Boto3 calls**: Violates separation of concerns, results in duplicated retry and timeout logic, prevents centralized token attribution, and lacks unified semantic caching.

### 4. What happens at 10M users?
The Centralized AI Gateway intercepts high-volume repetitive queries via the Redis Semantic Cache (absorbing 35% of AI traffic), routes 65% of remaining queries to low-cost Claude 3.5 Haiku, and routes only complex deep research memos to Claude 3.5 Sonnet, keeping total LLM operating costs within manageable boundaries.

### 5. What happens if the component fails?
- The AI Gateway implements circuit breaking. If Bedrock in `us-east-1` experiences 5xx errors or throttling, the gateway automatically falls back to secondary Bedrock regions (`us-west-2` or `eu-central-1`).
- If Claude 3.5 Sonnet is degraded, the gateway falls back to Claude 3.5 Haiku or verified cached summaries.

### 6. How does it scale?
Scales via AWS Bedrock **Provisioned Throughput (PT)** units for predictable baseline capacity + On-Demand units for burst traffic handling.

### 7. What is the operational cost?
With semantic caching and tiered routing (70% Haiku / 30% Sonnet), estimated monthly token spend is ~$50,000–$75,000 at target scale under 1-Year Provisioned Throughput commitments (compared to $200,000+ without caching).

### 8. What is the AWS production equivalent?
**AWS Bedrock Runtime API** with **Bedrock Guardrails** and **Provisioned Throughput**.

### 9. What is the local-development equivalent?
Local AI Gateway mock provider returning deterministic institutional responses and pseudo-embeddings, requiring zero AWS credentials or cloud costs during local development.
