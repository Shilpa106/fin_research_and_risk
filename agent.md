# Agent Guide — Enterprise Financial Research & Risk Copilot

This file is the operating manual for AI coding agents working in this repository. Read `context.md` for product and architecture background. Read `architecture/` for diagrams.

---

## Mission

This is an **institutional, multi-tenant GenAI platform** for investment banks, asset managers, and risk committees. It turns SEC filings, transcripts, and market data into grounded research, quantitative risk (VaR, stress tests), and auditable compliance workflows.

Every change must preserve:

1. **Tenant isolation** — no cross-tenant reads, writes, retrieval, or tool results.
2. **Grounded finance** — no uncited factual claims; quantitative math belongs in deterministic tools, not free-form LLM text.
3. **Governance** — high-risk actions pause at Human-in-the-Loop (HITL); agent loops have budgets, timeouts, and termination reasons.
4. **No secrets in source** — credentials come from environment / AWS Secrets Manager. Never commit `.env` secrets, keys, or production connection strings.

---

## Stack and layout

| Layer | Path | Responsibility |
|---|---|---|
| API | `src/api/` | FastAPI factory, middleware, `/api/v1` routers |
| Config | `src/config/` | Pydantic v2 settings from `.env` |
| Domain | `src/domain/` | SQLAlchemy entities, enums, exceptions |
| Application | `src/application/` | DTOs, services, ingestion pipeline |
| Infrastructure | `src/infrastructure/` | DB, Redis, S3/local storage, SQS/local queue, repositories |
| Security | `src/security/` | JWT, RBAC, request context, GenAI guardrails |
| Agents | `src/agents/` | LangGraph orchestrator and specialist nodes |
| RAG | `src/rag/` | Hybrid OpenSearch retrieval, chunking, citations, tenant filter |
| MCP | `src/mcp/` | Tool gateway and research / market / portfolio servers |
| AI Gateway | `src/ai_gateway/` | Model routing, cache, circuit breaker, token budget |
| Observability | `src/observability/` | JSON logs, correlation IDs, metrics, tracing |
| Evaluation | `src/evaluation/` | RAG / agent / safety eval and CI regression gate |
| Workers / events | `src/workers/`, `src/events/` | Ingestion workers and document event schemas |
| Infra as code | `terraform/` | AWS modules for `dev` / `staging` / `prod` |
| Tests | `tests/unit/`, `tests/integration/` | Pytest + pytest-asyncio |
| Docs / ADRs | `docs/`, `docs/adr/` | Architecture and decision records |

Python **3.11+**. Line length **120**. Ruff + Mypy. FastAPI `Depends` in defaults is allowed (Ruff `B008` ignored).

---

## How to run and verify

Local API (SQLite, no cloud keys required):

```powershell
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Health: `GET /health`, `GET /health/live`, `GET /health/ready`. Swagger: `http://127.0.0.1:8000/docs`.

Common commands (also in `Makefile`):

```powershell
python -m pytest -v
python -m pytest tests/unit -v
ruff check src/ tests/
ruff format src/ tests/
mypy src/
python -m src.evaluation.cli --fail-on-regression
```

Full local stack: `docker-compose up -d` (PostgreSQL 16, Redis, OpenSearch, API).

Do **not** run `terraform apply` unless the user explicitly asks.

---

## Architecture rules for new code

### Layering

- HTTP stays in `src/api/`. Business use-cases live in `src/application/services/`. Persistence in repositories. Domain entities stay free of FastAPI.
- Depend on interfaces in `src/interfaces/` (AI gateway, cache, embedding, queue, retriever, storage) rather than concrete AWS clients in application code.
- Local implementations exist for offline/dev: SQLite, `MockLLMProvider`, local storage, local queue, in-memory LangGraph checkpointer.

### Multi-tenancy (non-negotiable)

- Every tenant-owned row and chunk carries `tenant_id`.
- PostgreSQL: set RLS with `set_tenant_rls_context(session, tenant_id)` (`SET LOCAL app.current_tenant_id`) on PostgreSQL connections.
- OpenSearch: always inject a mandatory tenant term filter (`src/rag/tenant_filter.py`). Never accept a caller-supplied tenant that differs from the JWT context.
- MCP tools must use `ToolSecurityContext` and fail closed on missing tenant / permission (`TenantIsolationViolationException`).
- Tests that matter: `tests/integration/test_security_isolation.py`.

### Auth and RBAC

- JWT from `src/security/auth.py`. Request principal is `RequestSecurityContext`.
- Protect routes with `Depends(require_permissions("resource:action"))`.
- Roles: `ADMIN`, `ADVISOR`, `ANALYST`, `RISK_MANAGER`, `READ_ONLY_USER` in `src/security/rbac.py`.
- HITL approve/review requires `hitl:approve` / `hitl:review` (risk manager / admin). Do not grant HITL to analysts.

### Agents and tools

- Orchestration is a **LangGraph StateGraph** in `src/agents/orchestrator.py`, not a mega-prompt with unbounded tools.
- Nodes: supervisor → research / risk / portfolio specialists → synthesizer → validator → termination.
- Typed state: `src/agents/state.py` (`AgentState`). Extend state fields deliberately; keep tenant_id and permissions on every run.
- Termination guards must remain: HITL, timeout, token budget, cost budget, max iterations, tool failure limit, no-progress hash.
- Agents never call AWS or HTTP APIs directly. They go through **MCP Gateway** (`src/mcp/gateway.py`) with allowlists (`src/agents/tool_guard.py`, `src/mcp/security.py`).
- LLM calls go through **AI Gateway** (`src/ai_gateway/`). Default provider is mock unless Bedrock is configured. Preserve circuit breakers, retries, semantic cache, and tenant rate limits.

### RAG and citations

- Pipeline: query process → dense + BM25 → fusion → rerank → dedupe → compress → citations (`src/rag/retrieval_service.py`).
- Indexing must reject chunks whose `tenant_id` does not match the caller tenant.
- Output guardrails should reject ungrounded / ghost citations (`src/security/guardrails/output_guard.py`).

### Guardrails

`GenAISecurityManager` covers input, retrieval, agent, and output. Wire new copilot paths through it. Do not bypass input evaluation for “internal” prompts that still originate from users.

### Observability and audit

- Keep `CorrelationIdMiddleware` and structured JSON logging.
- Do not log raw prompts, PII, JWT secrets, or full document bodies. Use `src/observability/sanitizer.py`.
- Agent runs should remain reconstructable via trajectory (`src/agents/trajectory.py`) and audit repositories.

---

## Current wiring (do not assume)

Some product surfaces are **implemented as modules** but **not fully connected** on the HTTP path:

- `POST /api/v1/copilot/chat` currently runs input/output guardrails and returns a preview acknowledgment. It does **not** yet invoke `AgentOrchestrator`.
- `POST /api/v1/research/search` injects the tenant filter then returns empty hits.
- `POST /api/v1/risk/var` returns a baseline parametric estimate, not the full MCP portfolio engine.

When asked to “make chat work end-to-end”, wire API → security manager → orchestrator → RAG/MCP/AI gateway → HITL → output guards. Do not reimplement those subsystems.

Conversation create/list, document ingest services, HITL task lifecycle, LangGraph, RAG engine, MCP servers, AI gateway, and evaluation **are** real code with tests.

---

## Adding features — default placement

| If you are adding… | Put it in… |
|---|---|
| REST route | `src/api/v1/endpoints/` and register in `src/api/v1/router.py` |
| Request/response schema | `src/application/dtos.py` |
| Use-case | `src/application/services/` |
| Table / enum | `src/domain/entities.py` + Alembic under `alembic/versions/` |
| Repository | `src/infrastructure/repositories/` |
| Agent node | `src/agents/specialists/` and register in the StateGraph |
| MCP tool | existing server or new `src/mcp/servers/` + gateway register |
| Guardrail | `src/security/guardrails/` |
| Metric / span | `src/observability/` |
| Test | `tests/unit/` for pure logic; `tests/integration/` for API, isolation, graphs, MCP |

Database migrations: Alembic. Local SQLite auto-creates schema on startup in `development` / `test` only (`init_db_schema`). Production must use migrations.

---

## Testing expectations

- Match existing pytest-asyncio style in `tests/conftest.py`.
- Prefer tests that fail closed: wrong tenant, missing permission, prompt injection, ghost citation, MCP allowlist miss, HITL pause.
- Do not add tests that require live Bedrock, live OpenSearch clusters, or production AWS unless the user asks and credentials are already configured.
- After behavior changes, run the relevant unit/integration tests. For agent/RAG/security work, also run `tests/integration/test_agent_orchestration.py`, `test_retrieval_service.py`, `test_mcp_gateway.py`, `test_genai_security.py`, `test_hitl_workflow.py`.

---

## Explicit do-nots

- Do not weaken RLS, tenant filters, or MCP allowlists to “make a demo pass”.
- Do not put LLM-generated numbers in place of MCP/risk engine outputs.
- Do not hardcode production AWS account IDs, secrets, or real client portfolio data in fixtures.
- Do not expand copyrighted SEC filing text into the repo; use small synthetic excerpts in tests.
- Do not skip Ruff/Mypy locally invented style (e.g. 80-char lines, new formatters).
- Do not commit `__pycache__`, `.db` files, or evaluation artifacts unless requested.
- Do not invent new top-level packages when an existing module already owns the concern.

---

## Documentation map

- Product scale and quickstart: `README.md`, `readme_application.md`
- Capability list: `docs/requirements.md`
- Sizing and topology: `docs/architecture/system_design.md`
- Visual architecture (this work): `architecture/`
- ADRs: `docs/adr/`
- Interview-depth explanations: `docs/interview/`
- Project snapshot for agents: `context.md`
