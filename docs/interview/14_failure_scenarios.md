# 14 — Production Failure Scenarios & Resilience Engineering

## 1. Matrix of High-Impact Production Failure Modes

| Failure Scenario | Immediate System Behavior | Automated Mitigation & Recovery Mechanism | User & Operator Impact |
|---|---|---|---|
| **1. AWS Bedrock Outage / Throttling** | Primary model requests return HTTP 429 or timeout (>10s) | AI Gateway circuit breaker trips to `OPEN`; traffic automatically fails over to Claude 3.5 Haiku or secondary AWS region | Graceful degradation; slight reduction in reasoning depth, 100% platform availability maintained |
| **2. OpenSearch Cluster Degradation** | Vector & BM25 queries fail with connection timeout | Retrieval service falls back to semantic cache in Redis; if cache misses, returns transparent degraded warning | System refuses to hallucinate financial numbers; warns user that real-time filing retrieval is temporarily offline |
| **3. External Tool / API Hangs (SEC EDGAR)** | Tool HTTP request pauses on remote network socket | MCP Client enforces hard `asyncio.wait_for(timeout=5.0)`; cancels task and returns structured JSON error to agent | Agent receives structured timeout diagnostic; reflects and uses historical cached filings |
| **4. Database Connection Pool Exhaustion** | Concurrent traffic surges exceed direct pool limit | In production, AWS RDS Proxy absorbs and queues connections; in application, `pool_pre_ping=True` and async context manager reclaims idle connections | Queries experience transient queue wait rather than crashing with `FATAL: too many connections` |
| **5. Availability Zone (AZ) Outage** | One of 3 AWS data centers loses power or network | ALB stops routing to unhealthy targets; Aurora & Redis fail over to replicas in surviving AZs; ECS reschedules tasks | Brief <30s connection blip during leader election; zero data loss; full platform recovery |
| **6. Poisoned / Malicious Document Upload** | Uploaded filing contains hidden indirect prompt injection | Structure parser strips non-printable characters and scripts; XML-escaped data tags prevent instruction execution; tool guards block unauthorized calls | Injected instructions treated as inert text; security audit event emitted |
| **7. Agent Infinite Reasoning Loop** | Model repeatedly calls tools without reaching termination | LangGraph conditional edge checks `iteration_count >= 10` or tool repetition; forces transition to `synthesizer` node | Execution halts deterministically; partial findings returned; zero unbounded cloud billing |
| **8. Host OS Ephemeral Port Exhaustion** | Extreme concurrency (>16K sockets) exhausts TCP ports | In production, CloudFront edge caching and ALB HTTP/2 multiplexing distribute connections across 50 ECS tasks | Eliminates single-host port exhaustion; ALB reuses persistent keep-alive backhaul connections |

---

## 2. In-Depth Spoken Interview Responses

### Interviewer: "What happens when AWS Bedrock completely goes down?"
**Spoken Response:**
"When you build a mission-critical financial copilot, you cannot treat model providers as infallible. In our architecture:

1. **Failure Detection**: When our primary model (Claude 3.5 Sonnet on AWS Bedrock) begins returning HTTP 500 errors, 503 throttling errors, or exceeds our 10-second request timeout, our `CircuitBreaker` in `src/ai_gateway/circuit_breaker.py` tracks consecutive failures.
2. **Automated Fallback**: After 3 failures within a 30-second window, the circuit breaker opens. The gateway immediately redirects subsequent completion requests to our configured fallback model: Claude 3.5 Haiku (or a secondary AWS Bedrock region like `us-west-2`).
3. **Graceful User Notification**: In the response metadata, the platform appends a system notice: `{'model_used': 'anthropic.claude-3-5-haiku', 'provider_status': 'fallback_active'}`. The user receives their quantitative risk analysis without interruption.
4. **Self-Healing Canary**: After 60 seconds, the circuit breaker enters `HALF_OPEN` state, testing 10% of requests against Claude 3.5 Sonnet. As soon as AWS Bedrock recovers, traffic shifts back to the primary model automatically."

### Interviewer: "What happens when OpenSearch is unavailable? Does your copilot start hallucinating?"
**Spoken Response:**
"Under no circumstances does our copilot hallucinate when retrieval fails. We explicitly engineered the system with a **Fail-Safe Grounding Principle**:

1. **Catching Retrieval Failures**: In `src/rag/retrieval_service.py`, any `ConnectionError` or `TransportError` from the OpenSearch cluster is caught in an isolated try-catch block.
2. **Cache Check**: The service checks ElastiCache Redis to see if the exact financial filing query was previously cached. If a warm cache entry exists, it serves the cached chunks.
3. **Deterministic Degraded Mode**: If no cached chunks exist, the retrieval service returns an empty chunk list with an explicit error flag: `retrieval_status: 'UNAVAILABLE'`.
4. **Model Prompt Guardrail**: When the LangGraph Research Agent sees an empty context with `retrieval_status: 'UNAVAILABLE'`, our system prompt strictly forbids speculative answers. The agent outputs: *'The SEC filing retrieval subsystem is currently undergoing maintenance. I cannot access the FY2023 Form 10-K to verify this credit agreement. For compliance safety, I cannot provide this calculation without primary source filings.'* We prioritize zero hallucinations over an ungrounded guess."

### Interviewer: "What happens if a background document ingestion job fails midway through parsing a 500-page 10-K filing?"
**Spoken Response:**
"Document ingestion in `src/workers/ingestion_worker.py` is engineered around **Idempotency, Checkpointed Transactions, and Dead-Letter Queues (DLQ)**:

1. **SQS Ingestion Queue**: Document ingestion tasks are decoupled via AWS SQS with a 5-minute visibility timeout and a DLQ configured with `maxReceiveCount = 3`.
2. **Idempotency Fingerprint**: Every task payload contains a cryptographic `content_hash` and `document_id`. If a worker picks up a retry of an already-processed document, it checks PostgreSQL and exits immediately without duplicate processing.
3. **Granular Chunk Transactions**: Chunks are processed and indexed in atomic batches of 50. If a worker process crashes on page 350, the database tracks the last successfully indexed chunk index.
4. **Automatic Redrive to DLQ**: If a document repeatedly crashes the worker (for example, a corrupted PDF or malicious malformed XML), SQS moves the message to the `copilot-ingestion-dlq` dead-letter queue after 3 failed attempts. A CloudWatch alarm (`sqs-dlq-not-empty`) fires immediately to page SREs, while the primary ingestion pipeline continues processing subsequent filings without blocking."
