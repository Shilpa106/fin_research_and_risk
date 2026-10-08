# Project Context — Enterprise Financial Research & Risk Copilot

Durable context for humans and coding agents. Pair with `agent.md` (how to change the code) and `architecture/` (diagrams).

---

## What this product is

An **institutional-grade, multi-tenant AI copilot** for global investment banks, hedge funds, asset managers, and risk committees.

It converts unstructured financial documents (SEC 10-K / 10-Q / 8-K, earnings transcripts, research memos) and market data into:

- Grounded investment research with citations
- Quantitative risk (parametric / historical / Monte Carlo VaR, expected shortfall, macro stress tests)
- Portfolio exposure and concentration analysis
- Human-gated, auditable recommendations (SEC / FINRA-oriented controls)

It is **not** a general chatbot. Hallucinated math, cross-tenant leakage, and unvetted autonomous actions are treated as production incidents.

---

## Design targets

| Metric | Target |
|---|---|
| Registered users | 10 million |
| Monthly active users | 2 million |
| Peak concurrent users | 100,000 |
| Peak API RPS | 10,000 |
| Peak AI RPS | 500–1,000 |
| Document corpus | 100M+ filings (~25+ TB) |
| Searchable chunks | 1B+ in OpenSearch |
| Availability | 99.99% |

AI traffic is absorbed in tiers: Redis exact/semantic cache (~35% target hit rate) → Haiku triage → Sonnet deep reasoning → async workers for long memos.

---

## Who uses it

| Role (code: `RoleType`) | Typical work |
|---|---|
| `ANALYST` | Ingest documents, RAG search, copilot research, evaluation reads |
| `ADVISOR` | Conversations, research tools, portfolio read, limited risk |
| `RISK_MANAGER` | VaR / stress, HITL review and approve, audit read |
| `ADMIN` | Tenant administration, users/roles, full permissions (`*`) |
| `READ_ONLY_USER` | Published research and portfolio read |

Tenants are institutions (`Tenant`), tiered `starter` / `professional` / `enterprise` / `sovereign`, with per-tenant rate limits and optional dedicated OpenSearch index / KMS key.

---

## Technology choices (accepted)

| Concern | Choice | Why (short) |
|---|---|---|
| API | FastAPI + Uvicorn | Async 10K RPS class HTTP, OpenAPI, SSE-friendly |
| Relational data | PostgreSQL + RLS (Aurora Serverless v2 in prod; SQLite locally) | Kernel-level tenant isolation, ACID for HITL/audit |
| Cache / rate limit | Redis 7 | Token bucket, semantic cache, sessions |
| Search | OpenSearch 2.x hybrid BM25 + k-NN | 1B chunks, lexical finance terms + dense vectors |
| LLM | AWS Bedrock Claude 3.5 Sonnet / Haiku, Titan embeddings | Managed, Guardrails, no keys in app for model APIs |
| Agents | LangGraph StateGraph | Cycles, checkpoint, HITL interrupt, typed state |
| Tools | MCP gateway (in-process servers) | Allowlists, schema validation, no raw agent HTTP |
| Objects | S3 (MinIO/local in dev) | Filings, WORM-style audit retention |
| Messaging | SQS / Kafka (MSK) in design; local queue in code | Ingestion and audit fan-out |
| Infra | Terraform AWS (`dev`/`staging`/`prod`) | Multi-AZ VPC, ECS, WAF, KMS |
| Eval | In-repo RAG triad, trajectory, safety gates | CI regression on faithfulness / leakage |

ADRs live in `docs/adr/` (FastAPI, PostgreSQL RLS, OpenSearch, Redis, AI gateway, MCP, LangGraph, S3, Kafka).

---

## Runtime topology (production intent)

```
Clients (TLS)
  → CloudFront + WAF + ALB
    → ECS FastAPI fleet (24–40 tasks)
         → Redis (rate limit + semantic cache)
         → AI Gateway → Bedrock (+ Guardrails)
         → LangGraph orchestrator
         → Retrieval service → OpenSearch
         → MCP tools (research, market, portfolio)
         → Aurora PostgreSQL (RLS)
         → S3 / SQS
```

Local: single Uvicorn process + optional Docker Compose (Postgres, Redis, OpenSearch). LLM defaults to `MockLLMProvider` so the stack runs without AWS keys.

---

## Request lifecycle (intended production path)

1. **Edge** — TLS, WAF (injection / abuse), ALB.
2. **API middleware** — correlation ID, structured request log, CORS, JWT → `RequestSecurityContext` (`tenant_id`, `user_id`, roles, permissions).
3. **Input guardrails** — prompt injection, size caps, PII redaction (`GenAISecurityManager.evaluate_input`).
4. **Supervisor** — LangGraph classifies intent; selects research / risk / portfolio specialists; initializes budgets and deadline on `AgentState`.
5. **Research** — query rewrite → hybrid retrieve (tenant filter compulsory) → rerank → citations.
6. **Risk / portfolio** — MCP tools for prices, holdings, VaR, sector exposure; deterministic numbers, not LLM arithmetic.
7. **HITL gate** — if VaR / concentration / MNPI / guardrail flags trip, persist `HITLReviewTask`, pause graph (`HUMAN_APPROVAL_REQUIRED`), notify reviewers. Resume after `approve` / `reject`.
8. **Synthesizer + validator** — draft report, ground claims, loop on `REVISE` until approved or no-progress halt.
9. **Output guardrails** — citations exist, disclaimers, no PII/exfil.
10. **Audit + telemetry** — trajectory, token/cost, Prometheus/OTel spans. Never log raw secrets or full prompts.

---

## Code map (where truth lives)

### HTTP (`src/api/`)

- App factory: `src/api/main.py` (`create_app`, lifespan init/dispose).
- Versioned router prefix `/api/v1`: auth, copilot, research, risk, hitl, evaluation, observability, health.
- Dependencies: `src/api/dependencies.py`.
- Middleware: correlation, request logging, error handlers mapping `BaseAppException`.

### Domain (`src/domain/entities.py`)

Core tables/types: `Tenant`, `User`, memberships, `Role` / `Permission`, `Document`, chunks/ingestion status, portfolios, `HITLReviewTask`, conversations, agent runs, audit events.

Enums used everywhere: `RoleType`, `TenantTier`, `DocumentType`, `IngestionStatus`, `HITLReviewStatus`, `HITLTriggerReason`.

### Agents (`src/agents/`)

- `orchestrator.py` — StateGraph, termination guards, `run` / resume with checkpointer.
- `state.py` — `AgentState`, `TerminationReason`, `ValidationStatus`.
- Specialists: `supervisor`, `research_agent`, `risk_agent`, `portfolio_agent`, `synthesizer`, `validator`.
- `trajectory.py` — step log for audit/eval.
- Default checkpointer: `InMemorySaver` (local); production intent is PostgreSQL checkpointer.

### RAG (`src/rag/`)

Chunking (section-aware SEC items), embeddings, OpenSearch hybrid store, query processor, RRF fusion, cross-encoder rerank, compression, citation tracker, tenant filter guard.

### MCP (`src/mcp/`)

Gateway registers:

- `ResearchServer` — `search_research`, company reports, earnings
- `MarketDataServer` — price, history, market cap, volatility
- `PortfolioServer` — get portfolio/position, exposure, sector concentration

All tools have Pydantic I/O, RBAC permission, role allowlist, timeout and tenant RPM limits.

### AI Gateway (`src/ai_gateway/`)

Router by complexity (Haiku vs Sonnet vs embeddings), cache, rate limiter, token budget, circuit breaker, Bedrock provider + mock fallback.

### Security (`src/security/`)

JWT, password hashing, RBAC matrix, `RequestSecurityContext`, guards, audit helpers, layered GenAI guards (input / retrieval / agent / output).

### Data plane

- `src/infrastructure/database.py` — async engine, session, RLS setter, health, schema init for destaging.
- Repositories for users, tenants, documents, HITL, conversations, portfolios, agent runs, audit, evaluation.
- Ingestion: `src/application/ingestion/pipeline.py` + extractors + `workers/ingestion_worker.py`.

### Quality

- Tests: unit (config, domain, security, logging, interfaces) and integration (API, agents, RAG, MCP, HITL, isolation, eval, observability, ingestion).
- Eval CLI: `python -m src.evaluation.cli --fail-on-regression`.
- Load: `python -m src.benchmarks.load_tester` (local OS socket limits show up at 50K–100K CCU; production scale-out is ECS + ALB).

---

## Configuration

`src/config/settings.py` (`AppSettings`). Important variables:

| Variable | Role |
|---|---|
| `APP_ENV` | `development` / `staging` / `production` / `test` |
| `DATABASE_URL` | Default `sqlite+aiosqlite:///./financial_copilot_dev.db` |
| `JWT_SECRET_KEY` | HMAC; rotate in prod |
| `REDIS_URL` | Cache and rate limit |
| `OPENSEARCH_HOST` / `PORT` | Hybrid index `enterprise_financial_chunks_v1` |
| `BEDROCK_MODEL_ID` | Sonnet default |
| `BEDROCK_ROUTER_MODEL_ID` | Haiku |
| `BEDROCK_EMBEDDING_MODEL_ID` | Titan v2 |
| `SEMANTIC_CACHE_THRESHOLD` | Default 0.96 |

Production secrets: AWS Secrets Manager + KMS. `.env.example` is the template.

---

## Implementation honesty (as of this snapshot)

Fully built as libraries with tests: LangGraph orchestrator, hybrid RAG service, MCP gateway, AI gateway, guardrails, HITL service, ingestion pipeline, observability, evaluation, Terraform modules.

HTTP still **partially stubbed** on the happy path:

- Copilot chat acknowledges after guardrails; orchestrator is not mounted on that route yet.
- Research search applies tenant filter then returns zero hits (retrieval service exists separately).
- Risk VaR endpoint returns a baseline formula, not live MCP portfolio calc.

Treat “complete the copilot path” as **wiring and hardening**, not greenfield architecture.

---

## Non-functional constraints

- **Isolation**: RLS + OpenSearch routing/filter + MCP tenant context. Fail closed.
- **Latency intent**: metadata/search P95 tens of ms at API tier; conversational TTFT < 800 ms when streaming is enabled.
- **Cost**: semantic cache, Haiku for routing, token/cost budgets on `AgentState` and AI gateway.
- **DR intent**: multi-AZ; RTO < 15 min, RPO < 1 min (see `docs/disaster-recovery.md`).
- **Compliance flavor**: immutable audit, citations, disclaimers, HITL for high VaR / concentration / restricted lists.

---

## Related docs

| Doc | Use when |
|---|---|
| `README.md` | Scale overview, repo tree, quickstart |
| `readme_application.md` | Run, eval, load test, sample curl, Terraform |
| `docs/requirements.md` | 20 business capabilities |
| `docs/architecture/system_design.md` | Sizing math and Mermaid topology |
| `architecture/` | Visual C4-style and sequence diagrams |
| `docs/security-threat-model.md` | Threats and controls |
| `docs/hitl-workflow.md` | Approval lifecycle |
| `docs/event-architecture.md` | Streaming / ingestion events |
| `docs/observability.md` | OTel, metrics, logs |
| `docs/interview/` | Narrative explanations of design |
