# Enterprise Financial Research & Risk Copilot

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-E92063.svg)](https://docs.pydantic.dev/)
[![SQLAlchemy 2.0](https://img.shields.io/badge/SQLAlchemy-2.0-red.svg)](https://www.sqlalchemy.org/)
[![OpenSearch](https://img.shields.io/badge/OpenSearch-2.x-005BA6.svg)](https://opensearch.org/)
[![AWS Bedrock](https://img.shields.io/badge/AWS%20Bedrock-Claude%203.5-FF9900.svg)](https://aws.amazon.com/bedrock/)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-2D3748.svg)](https://langchain-ai.github.io/langgraph/)

An institutional-grade, multi-tenant AI copilot platform engineered for global investment banks, hedge funds, asset managers, and risk committees. The platform transforms SEC filings (10-K, 10-Q, 8-K), earnings transcripts, and real-time market data into high-fidelity investment research, quantitative risk models (Value-at-Risk, macro stress testing), and regulatory compliance audits.

---

## 1. System Scale & Design Targets

- **10 Million** Registered Users
- **2 Million** Monthly Active Users (MAU)
- **100,000** Peak Concurrent Users (CCU)
- **10,000** Peak API Requests/second (RPS)
- **500 – 1,000** Peak AI Requests/second
- **100M+** Financial Documents (25+ TB Corpus)
- **1B+** Searchable Chunks (OpenSearch 2.x Distributed Cluster)
- **99.99%** System Availability SLA (< 52.6 mins downtime/year)

---

## 2. Architecture Overview

```
Internet Clients (100K CCU)
         │  TLS 1.3
         ▼
[AWS CloudFront Edge] ──► [AWS WAF] ──► [AWS ALB (10,000 RPS)]
                                                │
       ┌────────────────────────────────────────┴────────────────────────────────────────┐
       ▼                                         ▼                                       ▼
[FastAPI Tasks (24-40)]                   [FastAPI Tasks]                         [FastAPI Tasks]
 (Async Uvicorn + uvloop)
       │
       ├──► [Redis Token-Bucket Rate Limiter] (10K RPS burst protection)
       │
       ├──► [Centralized AI Gateway]
       │       ├──► [Redis Semantic Cache] (>0.96 Cosine Sim, absorbs 35% AI traffic)
       │       ├──► [Bedrock Guardrails] (PII redaction & regulatory disclaimers)
       │       └──► [AWS Bedrock] (Claude 3.5 Sonnet / Haiku, Titan Embeddings)
       │
       ├──► [LangGraph Stateful Agent Runtime]
       │       ├──► [Supervisor / Router Node]
       │       ├──► [Financial Research Agent]
       │       ├──► [Quantitative Risk & VaR Agent]
       │       └──► [Human-in-the-Loop Interrupt Gate] ──► [PostgreSQL Checkpointer]
       │
       ├──► [Dedicated Retrieval Service] ──► [Amazon OpenSearch (24 Nodes, 1B+ Chunks)]
       │
       └──► [MCP Gateway & Tools] ──► [SEC EDGAR / Market Data / Risk Engines]
```

---

## 3. Repository Structure

```
├── .env.example                     # Environment configuration template (zero secrets)
├── Dockerfile                       # Multi-stage hardened production container build
├── docker-compose.yml               # Local stack (App, PostgreSQL, Redis, OpenSearch, MinIO)
├── Makefile                         # Task runner (dev, test, lint, format, typecheck)
├── pyproject.toml                   # Pinned project metadata, Ruff, Mypy, and Pytest config
├── alembic.ini                      # Database migration configuration
├── alembic/                         # Database migration scripts & environment
│   ├── env.py
│   └── script.py.mako
├── docs/                            # Complete enterprise architecture documentation suite
│   ├── requirements.md              # 20 business capabilities specifications
│   ├── architecture.md              # System architecture & Mermaid diagrams
│   ├── capacity-planning.md         # Mathematical sizing models (10M users, 1B chunks)
│   ├── security-architecture.md     # Zero Trust, PostgreSQL RLS, Bedrock Guardrails
│   ├── data-architecture.md         # OpenSearch schema, chunking pipeline, lifecycle
│   ├── api-architecture.md          # 10K RPS API design, rate limits, REST/SSE routes
│   ├── event-architecture.md        # Kafka event streaming, schemas, DLQ
│   ├── disaster-recovery.md         # Multi-AZ & Multi-Region HA (RTO < 15m, RPO < 1m)
│   ├── observability.md             # OpenTelemetry, Prometheus metrics, structured logs
│   ├── cost-architecture.md         # FinOps cost model, unit economics, savings plans
│   └── adr/                         # Architectural Decision Records (ADR-001 to ADR-009)
├── src/                             # Clean modular architecture
│   ├── api/                         # FastAPI entry point, routers, middleware, dependencies
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   ├── middleware/              # Correlation ID, structured logging, error handling
│   │   └── v1/                      # Versioned endpoints (health, copilot, research, risk, hitl)
│   ├── config/                      # Pydantic v2 settings & environment validation
│   ├── domain/                      # Core entities (Tenant, User, Document, HITL) & exceptions
│   ├── infrastructure/              # Database connection pool (Postgres RLS) & Redis pool
│   ├── application/                 # DTOs and application schemas
│   ├── security/                    # JWT authentication, password hashing, RBAC permissions
│   ├── observability/               # JSON logging, correlation IDs, Prometheus metrics
│   ├── agents/                      # LangGraph multi-agent financial state machine
│   ├── rag/                         # Hybrid vector/BM25 retrieval & chunking
│   ├── mcp/                         # Model Context Protocol tools & servers
│   ├── ai_gateway/                  # Centralized LLM gateway, caching, circuit breakers
│   ├── evaluation/                  # Automated RAG and agent evaluation harness
│   ├── workers/                     # Async document ingestion workers
│   └── events/                      # Kafka event schemas, producers, consumers
└── tests/                           # Test suite
    ├── conftest.py                  # Pytest async fixtures (aiosqlite & AsyncClient)
    ├── unit/                        # Fast isolated unit tests (config, logging, security, models)
    └── integration/                 # API integration tests (health, middleware, v1 endpoints)
```

---

## 4. Quickstart & Local Setup

### 4.1 Prerequisites
- Python 3.11 or 3.12+
- Docker and Docker Compose (optional for local multi-container stack)

### 4.2 Setup Local Environment
```bash
# 1. Clone repository and navigate to root
cd enterprise_financial_research_and_risk_copilot

# 2. Copy environment configuration template
cp .env.example .env

# 3. Create virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install alembic ruff mypy
```

### 4.3 Running the Local Development Server
```bash
# Start FastAPI application with auto-reload
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```
Interactive API documentation will be available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 4.4 Running with Docker Compose
To run the full stack including PostgreSQL, Redis, OpenSearch, and MinIO:
```bash
docker-compose up -d
```

---

## 5. Testing & Code Quality

Execute all unit and integration tests:
```bash
# Run all tests
python -m pytest -v

# Run only unit tests
python -m pytest tests/unit -v

# Run only integration tests
python -m pytest tests/integration -v
```

Execute static analysis and linting:
```bash
# Lint with Ruff
ruff check src/ tests/

# Format with Ruff
ruff format src/ tests/

# Type check with Mypy
mypy src/
```

---

## 6. Health & Ingress Probes

- `GET /health`: General application status, environment, and version.
- `GET /health/live`: Liveness probe for AWS ECS / Kubernetes process supervision.
- `GET /health/ready`: Readiness probe verifying live database and Redis connectivity.
