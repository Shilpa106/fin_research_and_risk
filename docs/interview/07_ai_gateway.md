# 07 — Enterprise AI Gateway & Multi-Model Routing

## 1. Component Analysis (9 Core Dimensions)

### 1. What Problem Does It Solve?
Enterprises adopting GenAI face model downtime, unpredictable token costs, vendor lock-in, and compliance challenges. Directly invoking LLM provider SDKs scatters API keys across code, prevents global rate limiting, lacks fallback resilience during provider outages, and makes centralized cost governance impossible.

### 2. Why Did We Choose This AI Gateway Architecture?
We built an in-house **Enterprise AI Gateway** (`src/ai_gateway/`) providing:
- **Unified Provider Abstraction**: A single, clean async interface (`BaseLLMProvider`) supporting AWS Bedrock, Anthropic direct, OpenAI, and testing mock providers.
- **Dynamic Model Fallback & Circuit Breaking**: Automatically routes traffic from primary high-tier models (Claude 3.5 Sonnet) to lightweight models (Claude 3.5 Haiku) upon transient failures.
- **Semantic Caching**: Employs Redis to cache deterministic completions, slashing latency to <5ms and eliminating redundant token costs.
- **Precise Cost & Token Tracking**: Logs exact prompt tokens, completion tokens, model names, and computed dollar costs per request, tenant, and conversation.

### 3. What Alternatives Were Considered?
- **LiteLLM Proxy / Portkey (External Sidecars)**: Considered, but running external proxy containers introduces an extra network hop and adds security compliance complexity for high-security financial data.
- **Direct Anthropic / OpenAI Python SDKs**: Rejected due to lack of fallbacks, vendor lock-in, and zero centralized cost control.
- **AWS Bedrock Only (Direct)**: While Bedrock is our primary production target, tying code solely to Bedrock prevented local developer testing without live AWS billing.

### 4. How Does It Work Internally?
```
Application / Agent Request
     │
     ▼
[AI Gateway Entrypoint]
     │
     ├── 1. Check Tenant Budget & Rate Limit (Redis sliding window)
     │       └─► If budget exceeded: Raise `TenantQuotaExceededException`
     │
     ├── 2. Check Semantic Cache (Redis prompt hash lookup)
     │       └─► Cache Hit? Return cached completion in 3ms
     │
     ├── 3. Execute Primary Provider (AWS Bedrock: Claude 3.5 Sonnet)
     │       │
     │       ├─► Success: Track tokens, record cost, cache result, return
     │       │
     │       └─► 429 Rate Limit / 5xx / Timeout (>10s):
     │             │
     │             ▼
     ├── 4. Trigger Circuit Breaker & Fallback Provider
     │       └─► Route to Secondary Model (AWS Bedrock: Claude 3.5 Haiku)
     │
     ▼
Emit OpenTelemetry Metrics (`llm.cost_usd`, `llm.tokens.input`, `llm.latency_ms`)
```

### 5. How Does It Scale?
- Fully stateless async execution.
- Connection pooling to AWS Bedrock endpoints using `httpx.AsyncClient` with keep-alive connections.
- Redis cache scales horizontally across ElastiCache nodes.

### 6. What Happens When It Fails?
- If all upstream LLM providers are unreachable (e.g., massive AWS regional outage), the circuit breaker opens, immediately rejecting requests with a fast fail (`503 Service Unavailable`) rather than hanging for 30 seconds.

### 7. How Is It Secured?
- Model credentials are not stored in environment variables; they are resolved via AWS IAM execution roles or encrypted AWS Secrets Manager keys.
- Input prompts and completions are scrubbed of credentials, API keys, and financial account numbers before structured logging.

### 8. How Is It Monitored?
- Metrics: `llm.requests.total`, `llm.tokens.input`, `llm.tokens.output`, `llm.latency_ms`, `llm.cost_usd`, `llm.cache.hit_ratio`.
- Logs: Structured JSON events recording provider name, model ID, response latency, and tenant attribution.

### 9. What Are the Trade-offs?
- **Semantic Caching Staleness**: Caching financial completions requires a short TTL (e.g., 1–4 hours) because real-time stock prices or market conditions change rapidly.

---

## 2. Spoken Interview Responses

### Interviewer: "How do you control and attribute LLM costs in a multi-tenant platform?"
**Spoken Response:**
"Uncontrolled token costs are one of the most common reasons enterprise GenAI pilots fail. In our platform, we enforce a **Three-Tier Cost Governance Model** built into `src/ai_gateway/cost_tracker.py`:

1. **Granular Model Pricing Tables**: We maintain exact pricing constants per 1,000 tokens for each model (e.g., Bedrock Claude 3.5 Sonnet at $3.00/1M input tokens and $15.00/1M output tokens; Claude 3.5 Haiku at $0.25/$1.25).
2. **Pre-Invocation Token Budget Check**: When a tenant issues a request, the gateway checks their monthly allocated budget in Redis. If the tenant has consumed their quota, the gateway rejects the request with HTTP 429 *'Tenant Monthly AI Budget Exceeded'*, preventing unexpected cloud bills.
3. **Real-Time Metering & Attribution**: Every single completion extracts `usage.prompt_tokens` and `usage.completion_tokens` from the raw response headers. We calculate the exact USD cost down to the micro-cent and attach it to both the database `ConversationMessage` record and our OpenTelemetry metrics registry tagged with `tenant_id` and `user_id`. This allows finance teams to generate exact cost-attribution chargebacks per department or client."

### Interviewer: "What happens when AWS Bedrock experiences an outage or throttles your requests?"
**Spoken Response:**
"If you rely on a single model endpoint without automated fallbacks, an upstream AWS throttling event (HTTP 429) immediately breaks your application and degrades user trust.

Our AI Gateway implements an automated **Circuit Breaker & Fallback Chain**:
1. When our primary model (Claude 3.5 Sonnet) encounters three consecutive timeouts or 429 rate limit exceptions within a 30-second sliding window, the circuit breaker trips from `CLOSED` to `OPEN`.
2. Traffic is immediately routed to our configured fallback: Claude 3.5 Haiku (or a secondary AWS region).
3. The fallback model processes the query. Because Haiku is an order of magnitude faster and significantly cheaper, it maintains platform availability during peak load.
4. After 60 seconds, the circuit breaker enters `HALF_OPEN` state, routing a small canary percentage of traffic back to Sonnet. If the canary calls succeed, the circuit resets to normal. The end user experiences zero service disruption."
