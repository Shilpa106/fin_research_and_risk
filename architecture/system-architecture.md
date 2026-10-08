# System architecture — Enterprise Financial Research & Risk Copilot

These diagrams describe the **intended production architecture** and the **code modules that implement it**. Local development substitutes SQLite, mock LLMs, in-memory LangGraph checkpoints, and optional Docker Compose for Postgres, Redis, and OpenSearch.

---

## 1. System context

Who uses the platform and which external systems it talks to.

```mermaid
flowchart LR
    subgraph Users["Institutional users"]
        PM["Portfolio managers"]
        RA["Research analysts"]
        RM["Risk managers / CRO"]
        CO["Compliance officers"]
        ADM["Tenant admins"]
    end

    COP["Financial Research & Risk Copilot"]

    subgraph External["External systems"]
        EDGAR["SEC EDGAR / filings"]
        MKT["Market data feeds"]
        IDP["SSO IdP: Okta / Entra / Ping"]
        BEDROCK["AWS Bedrock models & Guardrails"]
        SLACK["Slack / Teams / webhooks"]
    end

    PM --> COP
    RA --> COP
    RM --> COP
    CO --> COP
    ADM --> COP

    COP --> EDGAR
    COP --> MKT
    COP --> IDP
    COP --> BEDROCK
    COP --> SLACK
```

---

## 2. Container / runtime topology

Logical services as deployed on AWS (ECS FastAPI is the application process that hosts API, agents, RAG client, MCP gateway, and AI gateway in-process).

```mermaid
flowchart TB
    subgraph Edge["Edge & ingress"]
        C["Clients — 100K CCU"] -->|TLS 1.3| CF["CloudFront"]
        CF --> WAF["AWS WAF"]
        WAF --> ALB["ALB — 10K RPS"]
    end

    subgraph App["Application fleet — ECS Fargate"]
        ALB --> API["FastAPI / Uvicorn 24–40 tasks"]
        API --> MW["Correlation · JWT · RBAC · rate limit"]
        MW --> GW["AI Gateway"]
        MW --> LG["LangGraph orchestrator"]
        MW --> RET["Retrieval service"]
        MW --> MCP["MCP tool gateway"]
        MW --> HITL["HITL service"]
    end

    subgraph Data["Data & state"]
        API --> PG["Aurora PostgreSQL + RLS"]
        API --> REDIS["ElastiCache Redis"]
        RET --> OS["OpenSearch 2.x — 1B chunks"]
        API --> S3["S3 KMS documents & audit"]
        API --> Q["SQS / Kafka ingestion & DLQ"]
        LG --> PG
        HITL --> PG
        GW --> REDIS
    end

    subgraph Models["Foundation models"]
        GW --> SONNET["Claude 3.5 Sonnet"]
        GW --> HAIKU["Claude 3.5 Haiku"]
        GW --> TITAN["Titan Embeddings v2"]
        GW --> GRD["Bedrock Guardrails"]
    end
```

---

## 3. Application module map (code)

How `src/` packages relate. HTTP never talks to Bedrock or OpenSearch except through these modules.

```mermaid
flowchart TB
    API["src/api — FastAPI, middleware, v1 endpoints"]
    APP["src/application — services, DTOs, ingestion"]
    DOM["src/domain — entities, exceptions"]
    INF["src/infrastructure — DB, Redis, repos, S3, queues"]
    SEC["src/security — JWT, RBAC, GenAI guards"]
    AG["src/agents — LangGraph + specialists"]
    RAG["src/rag — hybrid retrieval + citations"]
    MCP["src/mcp — gateway + servers"]
    AIG["src/ai_gateway — router, cache, circuit breaker"]
    OBS["src/observability — logs, metrics, traces"]
    EVL["src/evaluation — RAG / agent / safety"]

    API --> SEC
    API --> APP
    API --> AG
    APP --> DOM
    APP --> INF
    AG --> AIG
    AG --> RAG
    AG --> MCP
    AG --> SEC
    RAG --> INF
    MCP --> DOM
    AIG --> OBS
    AG --> OBS
    API --> OBS
    EVL --> AG
    EVL --> RAG
```

---

## 4. LangGraph agent graph

Compiled in `src/agents/orchestrator.py`. Conditional edges after every specialist use `_route_after_step`. Any node may divert to `termination` when a guard fires.

```mermaid
stateDiagram-v2
    [*] --> supervisor: START

    supervisor --> research_agent: next_agent = research
    supervisor --> risk_agent: next_agent = risk
    supervisor --> portfolio_agent: next_agent = portfolio
    supervisor --> synthesizer: specialists done
    supervisor --> termination: budget / HITL / timeout

    research_agent --> risk_agent
    research_agent --> portfolio_agent
    research_agent --> synthesizer
    research_agent --> termination

    risk_agent --> synthesizer
    risk_agent --> termination: VaR / policy HITL
    portfolio_agent --> synthesizer
    portfolio_agent --> termination: concentration HITL

    synthesizer --> validator
    synthesizer --> termination: no progress

    validator --> synthesizer: REVISE
    validator --> termination: APPROVED or REJECTED

    termination --> [*]
```

**Termination reasons** (`TerminationReason`): `SUCCESS`, `MAX_ITERATIONS`, `TIMEOUT`, `TOKEN_BUDGET_EXCEEDED`, `COST_LIMIT_EXCEEDED`, `NO_PROGRESS`, `TOOL_FAILURE_LIMIT`, `HUMAN_APPROVAL_REQUIRED`, `UNRECOVERABLE_ERROR`.

---

## 5. Hybrid RAG pipeline

Implemented by `RetrievalService` (`src/rag/retrieval_service.py`). Tenant mismatch on index or query is a hard failure.

```mermaid
flowchart LR
    Q["User query + tenant_id + permissions"] --> QP["Query processor\nnormalize · intent · rewrite"]
    QP --> EMB["Embed query — Titan / mock"]
    QP --> FLT["Mandatory tenant term filter"]
    EMB --> VEC["k-NN dense search"]
    FLT --> BM25["BM25 lexical search"]
    VEC --> RRF["Reciprocal Rank Fusion"]
    BM25 --> RRF
    RRF --> RR["Cross-encoder rerank"]
    RR --> DD["Dedupe"]
    DD --> CMP["Context compressor"]
    CMP --> CIT["Citation tracker"]
    CIT --> LLM["Context to synthesizer / LLM"]
```

OpenSearch production sizing intent: ~24 data nodes, ~200 primary shards, ~1B chunks, routing key `tenant_{tenant_id}`.

---

## 6. MCP tool perimeter

Agents never receive unrestricted network access. `MCPGateway` discovers tools, checks allowlists, validates Pydantic schemas, enforces tenant RPM and timeouts.

```mermaid
flowchart TB
    AG["Specialist agent"] --> TG["Tool guard / allowlist"]
    TG --> GW["MCPGateway"]
    GW --> VAL["Schema + RBAC + tenant + injection checks"]

    VAL --> RS["ResearchServer\nsearch_research, company report, earnings"]
    VAL --> MS["MarketDataServer\nprice, history, cap, volatility"]
    VAL --> PS["PortfolioServer\nportfolio, position, exposure, sector"]

    RS --> OUT["ToolResult + audit event"]
    MS --> OUT
    PS --> OUT
    OUT --> AG
```

---

## 7. Defense in depth

```mermaid
flowchart TB
    subgraph Perimeter["Network & identity"]
        WAF["WAF / TLS"]
        JWT["JWT + short TTL"]
        RBAC["RBAC permission matrix"]
    end

    subgraph GenAI["GenAISecurityManager"]
        IN["Input guard — injection, PII, size"]
        RET["Retrieval guard — tenant, clearance, indirect injection"]
        AGT["Agent guard — tool allowlist, loops, cost"]
        OUT["Output guard — grounding, citations, disclaimer, exfil"]
    end

    subgraph DataIso["Data isolation"]
        RLS["PostgreSQL RLS SET LOCAL app.current_tenant_id"]
        OSF["OpenSearch compulsory tenant filter"]
        KMS["Per-tenant KMS / envelope encryption"]
    end

    subgraph Governance["Human & audit"]
        HITL["HITL interrupt + signed review"]
        AUD["Immutable audit + trajectory"]
    end

    WAF --> JWT --> RBAC --> IN --> RET --> AGT --> OUT
    RET --> RLS
    RET --> OSF
    AGT --> HITL
    OUT --> AUD
    RLS --> KMS
```

---

## 8. Document ingestion

```mermaid
flowchart LR
    SRC["Upload / Kafka / S3 batch"] --> HASH["SHA-256 tenant-scoped dedupe"]
    HASH --> CLS["Classify 10-K / 10-Q / 8-K / transcript"]
    CLS --> EXT["Extract + layout / tables"]
    EXT --> META["Ticker, CIK, fiscal period"]
    META --> CHK["Section-aware chunking"]
    CHK --> EMB["Embed"]
    EMB --> IDX["OpenSearch hybrid index"]
    IDX --> EVT["Document indexed event"]
    EXT -.-> DLQ["DLQ on failure"]
```

Code: `src/application/ingestion/pipeline.py`, `src/workers/ingestion_worker.py`, `src/events/document_events.py`.

---

## 9. Copilot sequence (intended end-to-end)

This is the target path for `POST /api/v1/copilot/chat`. Some HTTP handlers are still preview stubs; the modules below already exist.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant API as FastAPI + middleware
    participant SEC as Guardrails + RBAC
    participant ORCH as LangGraph orchestrator
    participant RAG as Retrieval service
    participant OS as OpenSearch
    participant MCP as MCP gateway
    participant AIG as AI gateway
    participant BR as Bedrock
    participant PG as PostgreSQL
    participant RM as Risk reviewer

    User->>API: POST /api/v1/copilot/chat
    API->>SEC: JWT, tenant, permissions, input guard
    SEC->>ORCH: AgentState tenant_id, budgets, deadline
    ORCH->>AIG: Supervisor routing (Haiku)
    AIG->>BR: Chat completion
    ORCH->>RAG: Research retrieve
    RAG->>OS: Hybrid query + tenant filter
    OS-->>RAG: Top chunks + citations
    ORCH->>MCP: calculate risk / get portfolio
    MCP-->>ORCH: Deterministic ToolResult
    alt VaR or policy breach
        ORCH->>PG: HITLReviewTask PENDING
        ORCH-->>User: HUMAN_APPROVAL_REQUIRED
        RM->>API: POST /hitl/tasks/{id}/approve
        API->>PG: APPROVED + resume checkpoint
    end
    ORCH->>AIG: Synthesize (Sonnet)
    AIG->>BR: Completion
    ORCH->>SEC: Output + citation guard
    SEC-->>User: Grounded report + disclaimer
```

---

## 10. AWS production (Terraform)

Modules under `terraform/modules/`, environments `dev` / `staging` / `prod`.

```mermaid
flowchart TB
    subgraph VPC["VPC — 3 AZs"]
        PUB["Public subnets — ALB"]
        PRIV["Private subnets — ECS tasks"]
        DATA["Data subnets — Aurora, Redis, OpenSearch"]
    end

    subgraph Compute["Compute"]
        ECS["ECS Fargate service"]
        ASG["Autoscaling: CPU, RPS, queue depth"]
    end

    subgraph Data["Managed data"]
        AUR["Aurora PostgreSQL Serverless v2"]
        EC["ElastiCache Redis replica group"]
        AOS["OpenSearch domain"]
        S3["S3 versioned + KMS"]
        SQS["SQS + FIFO + DLQ"]
    end

    subgraph Sec["Security & ops"]
        KMS["KMS CMK rotation"]
        SM["Secrets Manager"]
        WAF2["WAFv2 WebACL"]
        CW["CloudWatch + OTel"]
        R53["Route53"]
    end

    R53 --> WAF2 --> PUB --> ECS
    ECS --> PRIV
    ECS --> AUR
    ECS --> EC
    ECS --> AOS
    ECS --> S3
    ECS --> SQS
    ECS --> SM
    AUR --> DATA
    EC --> DATA
    AOS --> DATA
    ECS --> CW
    KMS --> S3
    KMS --> AUR
```

---

## 11. Local vs production mapping

| Concern | Local | Production |
|---|---|---|
| API | `uvicorn src.api.main:app` | ECS Fargate behind ALB |
| Database | SQLite `financial_copilot_dev.db` or Compose Postgres 16 | Aurora PostgreSQL Multi-AZ + RLS |
| Cache | Optional Redis / in-process | ElastiCache Redis |
| Search | Compose OpenSearch or in-memory test store | OpenSearch 24-node class cluster |
| LLM | `MockLLMProvider` | Bedrock Claude + Titan + Guardrails |
| Checkpointer | `InMemorySaver` | PostgreSQL checkpointer |
| Objects | Local filesystem | S3 + KMS |
| Queue | Local in-process queue | SQS / MSK |
| Secrets | `.env` dev key | Secrets Manager |

---

## 12. Scale numbers used in design

| Layer | Planning number |
|---|---|
| API tasks | 24–40 FastAPI containers, ~600 safe RPS each |
| AI absorber | ~35% Redis semantic cache (cosine > 0.96) |
| Chunk storage | ~12 KB/chunk → ~12 TB primary, ~32 TB allocated with replica + watermark |
| OpenSearch shards | ~200 primaries, ~60 GB/shard target |
| SLO | 99.99% availability; conversational TTFT target < 800 ms |
