# 13 — Enterprise Observability, OpenTelemetry & Distributed Tracing

## 1. Component Analysis (9 Core Dimensions)

### 1. What Problem Does It Solve?
Multi-agent GenAI systems are notoriously difficult to debug. When a user reports that a financial query returned an incorrect risk estimate, engineers must be able to trace the exact request across the ingress API, the orchestrator routing decision, the specific OpenSearch retrieval query, the reranker latency, the exact prompt sent to AWS Bedrock, the MCP tool call, and the database transaction. Without end-to-end distributed correlation, troubleshooting is impossible.

### 2. Why Did We Choose OpenTelemetry and Structured JSON Logging?
- **Universal Correlation Context**: Every request, coroutine, and agent step propagates a standardized 6-field context:
  - `request_id`, `trace_id`, `tenant_id`, `user_id`, `conversation_id`, `agent_run_id`.
- **OpenTelemetry Standard**: Vendor-neutral tracing and metrics that export seamlessly to AWS CloudWatch, Datadog, Prometheus, or LangSmith without vendor lock-in.
- **Strict Financial Privacy**: Zero-secret, zero-PII structured logging with automated redaction of sensitive credentials and account numbers.

### 3. What Alternatives Were Considered?
- **Proprietary Observability SDKs (e.g., Datadog only / New Relic only)**: Creates tight vendor coupling and expensive per-host licensing fees.
- **Unstructured Text Logs (`print` / standard python formatting)**: Unusable in production; log aggregators cannot parse or filter multi-tenant dimensions reliably.
- **LangSmith Only**: Excellent for LLM tracing, but lacks host-level infrastructure metrics (ECS CPU, database connections, SQS queue depth) required by enterprise SRE teams.

### 4. How Does It Work Internally?
```
HTTP Request Ingress ──► CorrelationIdMiddleware (ContextVars)
                               │
       ┌───────────────────────┼───────────────────────┐
       ▼                       ▼                       ▼
Structured JSON Logs    OpenTelemetry Traces    Prometheus / OTel Metrics
(RequestId, TenantId)   (Distributed Spans)     (Counters, Histograms)
       │                       │                       │
       ├── API Ingress         ├── Router Node         ├── API RPS & Latencies (p50/95/99)
       ├── Agent Steps         ├── Retrieval Span      ├── RAG Latencies & Cache Hit Ratio
       ├── MCP Invocations     ├── Tool Execution      ├── Agent Iterations & Success Rate
       └── LLM Completions     └── Bedrock LLM Call    └── LLM Token Counts & USD Cost
                                                       └── Infra CPU, Memory & DB Conns
```
- **Context Propagation**: Powered by Python's `contextvars` module. When FastAPI receives a request, `CorrelationIdMiddleware` initializes the context. Even when tasks yield inside asyncio event loops or spawn background coroutines, the correlation context is preserved.

### 5. How Does It Scale?
- OpenTelemetry metrics are recorded as atomic in-memory counters and histograms.
- Traces use configurable sampling (100% in dev/staging, 10% head-based sampling in production) to avoid overwhelming trace collectors during 10,000+ RPS surges.

### 6. What Happens When It Fails?
- If the telemetry exporter (e.g., CloudWatch OTel collector) is temporarily unreachable, logs and metrics buffer in memory with a ring-buffer drop policy so that observability failures never block the critical financial research path.

### 7. How Is It Secured?
- **Masking Filter**: In `src/observability/logging.py`, a custom JSON log formatter strips all occurrences of `Authorization`, `token`, `password`, `secret`, `ssn`, and `account_number`.
- Financial prompts containing private investment memos are hashed or truncated in standard application logs.

### 8. How Is It Monitored?
- Telemetry export health is monitored via the collector's own self-diagnostic metrics.

### 9. What Are the Trade-offs?
- **Tracing Overhead**: Full tracing on every LLM token generation adds small memory overhead. We mitigate this by tracing at the agent node and tool boundary rather than per-token streaming chunks.

---

## 2. Spoken Interview Responses

### Interviewer: "How do you trace an end-to-end request across multiple agents and tool calls?"
**Spoken Response:**
"In our architecture, every request is anchored by a unified correlation context managed via Python `contextvars`. 

Here is the exact operational flow:
1. When an HTTP request hits FastAPI, our `CorrelationIdMiddleware` checks for an existing `X-Request-ID` and W3C `traceparent` header. If absent, it generates a fresh UUID `request_id` and OpenTelemetry `trace_id`.
2. The user's authenticated `tenant_id` and `user_id` are injected into this context.
3. When the request enters LangGraph, the orchestrator generates an `agent_run_id`.
4. As the workflow transitions from the Research Agent to OpenSearch, an OTel child span (`rag.retrieval`) is created, automatically inheriting the parent `trace_id`.
5. When the Risk Assessor calls the MCP Gateway, another child span (`mcp.tool_execution`) is created with attributes: `tool.name: 'calculate_portfolio_risk'` and `tenant.id: tenant_123`.
6. When the model call is made to Bedrock, the AI Gateway records a `llm.completion` span with token counts and model latency.
7. If an issue occurs, an SRE or support engineer can take that single `request_id` from the client response, paste it into CloudWatch or Datadog, and immediately view the complete execution waterfall across every agent, tool, and database query in one correlated view."

### Interviewer: "How do you guarantee that sensitive financial data or client credentials never leak into your logs?"
**Spoken Response:**
"In banking, leaking client non-public personal information (NPI) or API secrets into logs is a severe regulatory violation under SOC2 and GLBA.

We enforce **Zero-Leakage Logging** at three programmatic checkpoints:
1. **Pydantic Model Secret Str**: In `src/config/settings.py`, all sensitive fields (database passwords, Redis auth tokens, encryption keys) are typed as Pydantic's `SecretStr`. Calling `str()` or printing the settings object automatically masks the value as `**********`.
2. **Custom JSON Log Formatter Filter**: In `src/observability/logging.py`, our logging formatter intercepts every log record dictionary before serialization. It recursively scans keys against a sensitive key denylist (`['password', 'token', 'authorization', 'secret', 'key', 'ssn', 'tax_id']`) and scrubs matching values.
3. **Structured Event Whitelisting**: We explicitly prohibit logging raw request bodies or unvetted prompt strings in standard application logs. Instead of `logger.info(f'User prompt: {prompt}')`, we emit structured events: `logger.info('Copilot prompt processed', extra={'prompt_length': len(prompt), 'tokens': 450})`. High-volume text is stored in encrypted, access-controlled audit tables in PostgreSQL, never in plaintext log streams."
