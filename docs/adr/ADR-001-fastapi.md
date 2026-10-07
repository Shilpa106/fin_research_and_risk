# ADR-001: FastAPI for High-Throughput API Gateway & Application Services

## Status
Accepted

## Context
The platform requires an API and application service framework capable of sustaining 10,000 peak API requests per second with 100,000 concurrent active users. The majority of requests involve asynchronous non-blocking I/O (Redis cache checks, PostgreSQL pooled transactions, OpenSearch hybrid queries, and streaming AI responses).

---

## Technical Evaluation (The 9 Architectural Dimensions)

### 1. Why this technology?
FastAPI is built natively on Starlette and `asyncio`, utilizing `uvloop` for high-performance non-blocking event loop execution. It provides native runtime schema validation via Pydantic v2 (implemented in Rust), automatic OpenAPI 3.1 documentation generation, native Server-Sent Events (SSE) and WebSocket support for LLM streaming, and an elegant dependency injection engine for multi-tenant context management.

### 2. What alternatives were considered?
- **Flask / Django (WSGI)**
- **Node.js (NestJS / Express)**
- **Go (Gin / Fiber)**
- **Java / Kotlin (Spring Boot Reactive / WebFlux)**

### 3. Why were they rejected?
- **Flask / Django**: Traditional synchronous WSGI workers block operating system threads during I/O waits. Handling 100,000 CCU would require thousands of heavy OS processes, leading to memory exhaustion and kernel context-switching thrashing.
- **Node.js**: Outstanding async concurrency, but completely disconnected from the Python AI/ML ecosystem (LangGraph, NumPy, SciPy, Pandas). Requiring cross-process RPC serialization between Node.js and Python adds 15–30ms latency per request and duplicates maintenance across two language runtimes.
- **Go / Spring Boot**: Excellent raw throughput, but lacks first-class support for state-of-the-art Python agentic frameworks (LangGraph, PyTorch).

### 4. What happens at 10M users?
User accounts and session state are strictly externalized to PostgreSQL and Redis. FastAPI instances remain completely stateless. At 10M users and 100K CCU, FastAPI scales horizontally by simply adding stateless container tasks behind the Application Load Balancer.

### 5. What happens if the component fails?
- Individual container crashes are caught by Docker/ECS health checks (`/health/live`).
- The AWS ALB automatically deregisters unhealthy tasks within 5 seconds and routes incoming requests to healthy tasks across 3 Availability Zones.
- Client requests experience zero downtime due to $N+2$ redundant container headroom.

### 6. How does it scale?
Horizontally via AWS ECS Service Auto Scaling using Target Tracking scaling policies:
- Target tracking metric 1: CPU utilization $> 60\%$.
- Target tracking metric 2: `ALBRequestCountPerTarget` $> 500$ requests/container.
- Containers scale out from 24 baseline tasks to 40+ tasks within 90 seconds.

### 7. What is the operational cost?
30 average ECS Fargate tasks (2 vCPU, 4 GiB RAM each) cost ~$2,800/month under AWS 3-Year Compute Savings Plans.

### 8. What is the AWS production equivalent?
FastAPI running on **AWS ECS Fargate / EC2** behind an **AWS Application Load Balancer (ALB)** with AWS WAF protection.

### 9. What is the local-development equivalent?
FastAPI running locally via `uvicorn src.api.main:app --reload` on `localhost:8000` with Python 3.11.
