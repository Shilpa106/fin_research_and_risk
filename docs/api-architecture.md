# Enterprise Financial Research & Risk Copilot — API Architecture

## 1. API Tier Overview & Ingress Design

The API tier is designed to sustain **10,000 API requests/second** at P95 latency $< 30\text{ ms}$ for transactional endpoints and $< 800\text{ ms}$ Time-To-First-Token (TTFT) for streaming AI endpoints.

```
Internet Clients (100K CCU)
         │  TLS 1.3
         ▼
[AWS CloudFront Edge] ──► [AWS WAF] ──► [AWS ALB (10K RPS)]
                                                │
       ┌────────────────────────────────────────┴────────────────────────────────────────┐
       ▼                                         ▼                                       ▼
[FastAPI Task 1]                          [FastAPI Task 2]                         [FastAPI Task N]
 (Async Uvicorn + uvloop)                  (Async Uvicorn + uvloop)                 (24 - 40 Tasks)
```

### 1.1 Ingress Routing & Load Balancing
- **Application Load Balancer (ALB)**: Operates across 3 AWS Availability Zones. Performs cross-zone load balancing, health checks (`/health/live`, `/health/ready`), and sticky session termination when required.
- **Connection Management**: HTTP/2 multiplexing reduces connection setup overhead. Idle connection timeout set to 65 seconds to exceed client keep-alive periods.

---

## 2. Rate Limiting & Quota Management (10K RPS Protection)

To safeguard downstream systems (Aurora PostgreSQL and Bedrock), an atomic **Token-Bucket Rate Limiter** runs on Redis at the API gateway layer:

```lua
-- Atomic Token Bucket Lua Script
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local current_time = tonumber(ARGV[2])
local refill_rate = tonumber(ARGV[3]) -- tokens per millisecond
local capacity = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last_updated')
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

if not tokens then
    tokens = capacity
    last_updated = current_time
else
    local elapsed = current_time - last_updated
    if elapsed > 0 then
        tokens = math.min(capacity, tokens + (elapsed * refill_rate))
        last_updated = current_time
    end
end

if tokens >= limit then
    tokens = tokens - limit
    redis.call('HMSET', key, 'tokens', tokens, 'last_updated', last_updated)
    redis.call('EXPIRE', key, 60)
    return 1 -- ALLOWED
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_updated', last_updated)
    redis.call('EXPIRE', key, 60)
    return 0 -- RATE LIMITED (429)
end
```

### Rate Limiting Tier Configuration

| Client Tier | Sustained RPS | Burst Capacity | AI Requests/Minute | Quota Scope |
| :--- | :--- | :--- | :--- | :--- |
| **Starter** | 100 RPS | 250 | 60 | Tenant-wide |
| **Professional** | 1,000 RPS | 2,000 | 300 | Tenant-wide |
| **Enterprise** | 5,000 RPS | 8,000 | 1,200 | Tenant-wide |
| **Sovereign Tier-1** | 10,000 RPS | 15,000 | 3,000 | Dedicated isolated cluster |

---

## 3. Communication Protocols: REST, SSE, & WebSockets

1. **Standard REST APIs (JSON / OpenAPI 3.1)**:
   - Used for metadata queries, user management, document uploads, portfolio configurations, and HITL decision submissions.
2. **Server-Sent Events (SSE)**:
   - Endpoint: `POST /api/v1/copilot/chat` with `Accept: text/event-stream`.
   - Streams incremental agent reasoning thoughts, inline citations, and generated report tokens in real time.
   - Resilient against network interruptions with automatic client reconnection and `Last-Event-ID` tracking.
3. **WebSockets (Bi-directional)**:
   - Endpoint: `WSS /api/v1/copilot/ws/{thread_id}`.
   - Used for interactive financial terminal sessions where analysts provide real-time clarifying guidance during multi-step financial modeling.

---

## 4. Complete API Route Catalog

### 4.1 Authentication & Tenants (`/api/v1/auth`)
- `POST /api/v1/auth/token`: Exchanges SAML/OIDC code or credentials for access/refresh tokens.
- `POST /api/v1/auth/refresh`: Rotates refresh token and issues new JWT.
- `POST /api/v1/auth/api-keys`: Issues new high-throughput M2M API key (Tenant Admin only).
- `GET  /api/v1/auth/me`: Returns current user identity, role, and tenant metadata.

### 4.2 Conversational AI Copilot (`/api/v1/copilot`)
- `POST /api/v1/copilot/chat`: Primary conversational endpoint. Supports both JSON blocking and SSE streaming modes.
- `GET  /api/v1/copilot/threads/{thread_id}`: Retrieves state and conversation history for an active thread.
- `DELETE /api/v1/copilot/threads/{thread_id}`: Archives/resets an agent conversation thread.

### 4.3 Financial Document Search & RAG (`/api/v1/research`)
- `POST /api/v1/research/search`: Executes hybrid vector + BM25 search across 1B+ chunks with tenant filtering.
- `POST /api/v1/research/compare`: Runs automated comparative analysis between two SEC filings (e.g. 2023 vs 2024 10-K Risk Factors).
- `GET  /api/v1/research/documents/{doc_id}`: Fetches raw document metadata and chunk index catalog.

### 4.4 Quantitative Risk & Portfolio Management (`/api/v1/risk`)
- `POST /api/v1/risk/var`: Computes Parametric, Historical, and Monte Carlo Value-at-Risk for portfolio positions.
- `POST /api/v1/risk/stress-test`: Runs macro stress test scenarios (2008 GFC, COVID-19, Rate Hikes).
- `GET  /api/v1/risk/portfolios/{portfolio_id}/factors`: Returns factor sensitivities (Beta, Duration, Convexity).

### 4.5 Human-In-The-Loop Management (`/api/v1/hitl`)
- `GET  /api/v1/hitl/tasks`: Lists pending review tasks requiring Risk Officer sign-off.
- `GET  /api/v1/hitl/tasks/{task_id}`: Fetches task details, draft report, and trigger metrics.
- `POST /api/v1/hitl/tasks/{task_id}/action`: Submits human decision (`APPROVE`, `REJECT`, `MODIFY`), resuming LangGraph thread.

### 4.6 Health & Infrastructure Telemetry (`/health`)
- `GET  /health/live`: Liveness probe (checks process execution).
- `GET  /health/ready`: Readiness probe (verifies PostgreSQL, Redis, and OpenSearch connectivity).
- `GET  /metrics`: Prometheus metric exposition endpoint (internal network only).

---

## 5. Request & Response Lifecycle & Middleware Pipeline

```
Incoming HTTP Request
       │
       ▼
[1. Correlation Middleware]  ──► Generates W3C TraceContext trace_id & sets contextvars
       ▼
[2. Observability Middleware] ──► Records request timer & increments Prometheus active_requests
       ▼
[3. Tenant Context Middleware]──► Validates JWT/API Key, extracts tenant_id, sets DB RLS session
       ▼
[4. Rate Limiter Middleware]  ──► Executes Redis token bucket check; returns 429 if exceeded
       ▼
[5. Request Route Handler]    ──► Executes controller logic, AI Gateway, or LangGraph workflow
       ▼
[6. Response Formatting]      ──► Injects X-Correlation-ID & X-RateLimit headers
       ▼
HTTP Response Returned
```
