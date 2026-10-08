# Enterprise Financial Research & Risk Copilot — Application Run Guide

This guide provides end-to-end instructions for running, testing, evaluating, and interacting with the **Enterprise Financial Research & Risk Copilot** platform.

---

## Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Option A: Quickstart Local Server (Zero Setup)](#2-option-a-quickstart-local-server-zero-setup)
3. [Option B: Full Enterprise Stack (Docker Compose)](#3-option-b-full-enterprise-stack-docker-compose)
4. [Environment Configuration (.env)](#4-environment-configuration-env)
5. [Interactive API Documentation & Health Probes](#5-interactive-api-documentation--health-probes)
6. [Running the Test Suites](#6-running-the-test-suites)
7. [Running the GenAI Evaluation & CI Regression Gate](#7-running-the-genai-evaluation--ci-regression-gate)
8. [Running the Empirical Scale & Concurrency Load Benchmark](#8-running-the-empirical-scale--concurrency-load-benchmark)
9. [End-to-End API Usage Walkthrough](#9-end-to-end-api-usage-walkthrough)
10. [Terraform AWS Cloud Deployment](#10-terraform-aws-cloud-deployment)
11. [Troubleshooting & FAQ](#11-troubleshooting--faq)

---

## 1. Prerequisites

- **Python**: Python 3.11 or Python 3.12+ installed
- **Operating System**: Windows (PowerShell / CMD), macOS, or Linux (Bash)
- **Docker & Docker Compose** *(Optional)*: Required only if running the containerized PostgreSQL, Redis, and OpenSearch stack

---

## 2. Option A: Quickstart Local Server (Zero Setup)

The repository includes a pre-configured `.env` file that runs in local development mode using an asynchronous SQLite engine (`./financial_copilot_dev.db`). The database schema is automatically checked and initialized on startup. **No external databases or cloud API keys are required to run locally.**

### Step 1: Start the FastAPI Server
Run the ASGI server with hot-reload enabled:

#### On Windows (PowerShell):
```powershell
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```

#### On Linux / macOS (Bash):
```bash
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```

### Step 2: Verify Server Health
Once launched, the server outputs:
```
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     Database schema initialized.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Test the health probe via terminal or browser:
```powershell
curl http://127.0.0.1:8000/health
```
**Expected Response:**
```json
{
  "status": "ok",
  "version": "1.0.0",
  "environment": "development",
  "timestamp": "2026-10-08T13:14:32.248209"
}
```

---

## 3. Option B: Full Enterprise Stack (Docker Compose)

To run the complete production topology locally (PostgreSQL 16, Redis 7.1, OpenSearch 2.11, and the FastAPI application):

```bash
# 1. Start all containers in the background
docker-compose up -d

# 2. Check container status
docker-compose ps

# 3. View live application logs
docker-compose logs -f app

# 4. Stop and remove containers when finished
docker-compose down
```

---

## 4. Environment Configuration (`.env`)

The local `.env` file is pre-configured with safe development defaults:

| Variable | Default Value | Description |
|---|---|---|
| `APP_ENV` | `development` | Application mode (`development`, `staging`, `production`, `test`) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./financial_copilot_dev.db` | Local async database connection string |
| `JWT_SECRET_KEY` | `dev-insecure-secret-key-change-in-production...` | HMAC key for signing JWT bearer tokens |
| `REDIS_URL` | `redis://localhost:6379/0` | In-memory cache & rate limiter endpoint |
| `OPENSEARCH_HOST` | `localhost:9200` | OpenSearch hybrid search endpoint |
| `AWS_REGION` | `us-east-1` | AWS region for Bedrock foundation models |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-5-sonnet-20241022-v2:0` | Primary multi-agent reasoning model |

*Note: In production environments, credentials are dynamically resolved via AWS Secrets Manager and KMS Customer Managed Keys.*

---

## 5. Interactive API Documentation & Health Probes

Open your browser to explore the interactive API:

- **Swagger UI (Interactive API Explorer)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc (Formal API Specification)**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **OpenAPI Schema (Raw JSON)**: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

### System Diagnostics Endpoints
```powershell
# Basic Liveness Probe (Returns HTTP 200 OK)
curl http://127.0.0.1:8000/health/live

# Readiness Probe (Verifies Database and Redis connectivity)
curl http://127.0.0.1:8000/health/ready

# Deep Diagnostic Probe (Inspects Database, Redis, and Metrics Registry)
curl http://127.0.0.1:8000/health/deep

# OpenTelemetry / Prometheus Metrics Endpoint
curl http://127.0.0.1:8000/api/v1/metrics
```

---

## 6. Running the Test Suites

The test suite contains **156 unit and integration tests** verifying security isolation, RAG retrieval, multi-agent graphs, MCP tools, and API middleware:

```powershell
# Run the fast unit test suite (18 tests, ~0.6 seconds)
python -m pytest tests/unit/

# Run the complete test suite (all 156 tests)
python -m pytest tests/

# Run with verbose output and coverage
python -m pytest -v
```

---

## 7. Running the GenAI Evaluation & CI Regression Gate

The evaluation platform benchmarks RAG metrics (Faithfulness, Context Recall, NDCG), agent trajectory accuracy, and safety guardrails (prompt injection and cross-tenant leakage defense) against golden datasets:

```powershell
python -m src.evaluation.ci_runner
```

*This command automatically validates that quality scores meet configured thresholds and generates `evaluation_report.md`.*

---

## 8. Running the Empirical Scale & Concurrency Load Benchmark

The benchmark runner executes real load-testing scenarios against the application across five concurrency tiers: 100 users, 1,000 users, 10,000 users, 50,000 users, and 100,000 concurrent connections:

```powershell
python -m src.benchmarks.load_tester
```

### Empirical Results Summary
| Concurrency Tier | Attempted | Succeeded | RPS | p50 Latency | Status | Note |
|---|---|---|---|---|---|---|
| **Tier 1: 100 Users** | 1,000 | 1,000 | 149.3 | 160.84 ms | **PASSED** | 100% Success, zero packet loss |
| **Tier 2: 1,000 Users** | 3,000 | 3,000 | 125.2 | 7,179.38 ms | **PASSED** | Single-worker event loop serialization |
| **Tier 3: 10,000 Users** | 10,000 | 10,000 | 172.8 | 24,687.62 ms | **PASSED** | Sustained throughput under high concurrency |
| **Tier 4: 50,000 Users** | 50,000 | 307 | 1.97 | 21,224.50 ms | **SATURATED** | Host OS ephemeral TCP port table limit reached |
| **Tier 5: 100,000 CCU** | 100,000 | 0 | 0.0 | — | **SOCKET_LIMIT** | OS socket starvation (16,384 port physical cap) |

*Full analysis and AWS production scale-out architecture available in [`docs/capacity-report.md`](docs/capacity-report.md).*

---

## 9. End-to-End API Usage Walkthrough

### 9.1 Register a User and Obtain a JWT Token

#### Step 1: Register an Institutional User
```powershell
curl -X POST http://127.0.0.1:8000/api/v1/auth/register `
  -H "Content-Type: application/json" `
  -d '{
    "email": "analyst@apexcapital.com",
    "password": "SecurePassword123!",
    "full_name": "Senior Quant Analyst",
    "tenant_name": "Apex Capital Management",
    "role": "analyst"
  }'
```

#### Step 2: Login to Receive the Bearer Token
```powershell
curl -X POST http://127.0.0.1:8000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{
    "email": "analyst@apexcapital.com",
    "password": "SecurePassword123!"
  }'
```
**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "tenant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

---

### 9.2 Execute Multi-Agent Financial Research & Risk Analysis

Submit a complex financial research query to the LangGraph multi-agent copilot:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/copilot/chat `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer <YOUR_ACCESS_TOKEN>" `
  -H "X-Tenant-ID: <YOUR_TENANT_ID>" `
  -d '{
    "message": "Analyze Apple FY2023 Form 10-K Item 1A risk factors and compute 95% Value-at-Risk under a 100bps interest rate shock."
  }'
```

---

### 9.3 Perform Human-in-the-Loop (HITL) Approvals

When an agent calculation exceeds a tenant's risk threshold (e.g., Value-at-Risk > 5%), the workflow automatically pauses at the `hitl_gate` node and creates a pending task.

#### View Pending High-Risk Tasks
```powershell
curl -X GET http://127.0.0.1:8000/api/v1/hitl/tasks `
  -H "Authorization: Bearer <YOUR_ACCESS_TOKEN>"
```

#### Approve the Pending Task
```powershell
curl -X POST http://127.0.0.1:8000/api/v1/hitl/tasks/<TASK_ID>/approve `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer <YOUR_ACCESS_TOKEN>" `
  -d '{
    "notes": "Approved by Chief Risk Officer after stress-test review"
  }'
```
*Approving the task automatically resumes the LangGraph execution graph from the persisted checkpointer to generate the final synthesized report.*

---

## 10. Terraform AWS Cloud Deployment

The production cloud infrastructure is fully codified in Terraform modules supporting `dev`, `staging`, and `prod` environments:

```powershell
# Navigate to the desired environment directory
cd terraform/environments/dev

# Initialize Terraform providers
terraform init

# Validate and preview infrastructure changes
terraform plan

# (Production deployment when authorized)
# terraform apply
```

Infrastructure provisioned includes:
- **Networking**: Multi-AZ VPC across 3 Availability Zones, dedicated NAT Gateways, strict Security Groups
- **Compute**: Application Load Balancer with Blue/Green Target Groups, ECS Fargate with 5 autoscaling policies
- **Database**: Aurora PostgreSQL Serverless v2 Multi-AZ (2 to 32 ACUs), ElastiCache Redis 7.1 replication group
- **Storage & Messaging**: S3 versioned buckets with KMS encryption, SQS primary & FIFO queues with DLQs
- **Edge & Security**: AWS WAF WebACL, CloudFront global CDN, Route53 DNS, AWS Secrets Manager

---

## 11. Troubleshooting & FAQ

### Port 8000 Already in Use
If port 8000 is occupied by another process, run on an alternative port (e.g., 8080):
```powershell
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8080 --reload
```

### Resetting the Local SQLite Database
To wipe the local development database and restart fresh:
```powershell
Remove-Item -Path ./financial_copilot_dev.db -Force
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```
*The database file and tables will automatically re-initialize upon startup.*

### Client Interview Preparation Resources
For in-depth architectural questions, system design walkthroughs, and spoken interview responses, review the 16-part interview preparation guide located in [`docs/interview/`](docs/interview/):
- [`01_project_introduction.md`](docs/interview/01_project_introduction.md) — Executive pitch & request lifecycle
- [`03_rag_deep_dive.md`](docs/interview/03_rag_deep_dive.md) — Hybrid RAG, OpenSearch vs pgvector, chunking
- [`05_langgraph.md`](docs/interview/05_langgraph.md) — StateGraph, checkpointing, and HITL interruption
- [`16_followup_questions.md`](docs/interview/16_followup_questions.md) — 23 difficult client follow-up questions with spoken responses
