# 10 — Database Architecture & Data Tier Engineering

## 1. Component Analysis (9 Core Dimensions)

### 1. What Problem Does It Solve?
Enterprise financial systems require strict ACID transaction guarantees for user tenancy, RBAC permissions, and immutable audit logs, while also demanding sub-millisecond response times for session token lookups, sliding-window rate limiting, and agent checkpointing. A single database technology cannot satisfy both relational ACID compliance and high-throughput sub-millisecond in-memory caching.

### 2. Why Did We Choose This Database Stack?
We engineered a **Polyglot Relational + In-Memory Tier**:
- **Aurora PostgreSQL 16 (Serverless v2)**: The primary transactional system of record. Offers sub-second compute autoscaling (2.0 to 32.0 ACUs), Multi-AZ automatic failover, and dedicated read replicas.
- **ElastiCache Redis 7.1 (Multi-AZ Replication Group)**: In-memory store for rate-limiting tokens, session validation, LangGraph state checkpoints, and semantic AI completion caching.
- **AsyncPG + SQLAlchemy 2.0 Async Engine**: High-performance non-blocking asynchronous database drivers powering the FastAPI event loop.

### 3. What Alternatives Were Considered?
- **NoSQL / DynamoDB / MongoDB**: Rejected as the primary store. Financial audit trails, multi-tenant RBAC hierarchies, and HITL task relationships require relational foreign keys, constraints, and ACID transactions.
- **Standard RDS PostgreSQL**: Lacks the sub-second autoscaling responsiveness of Aurora Serverless v2; requires static instance sizing that either over-provisions compute during off-market hours or crashes during sudden earnings release spikes.

### 4. How Does It Work Internally?
```
FastAPI Async Application
     │
     ├── Read/Write ACID Transactions ──► RDS Proxy ──► Aurora Serverless v2 (Writer)
     │                                                       │
     │                                              (Multi-AZ Replication)
     │                                                       ▼
     ├── Analytical / Report Reads    ──► RDS Proxy ──► Aurora Read Replica
     │
     └── In-Memory State & Caching   ──► ElastiCache Redis 7.1 (Primary + Replicas)
```
- **Domain Entities (`src/domain/entities.py`)**:
  - `Tenant`: Organization metadata, tier, rate limit ceilings, HITL risk thresholds.
  - `User`: Credentials, RBAC roles, tenant binding, MFA status.
  - `FinancialDocument`: Ingested filing metadata, S3 URI, SHA256 checksum, chunk counts.
  - `Conversation` & `ConversationMessage`: Chat session history, token counts, cost attribution, and cited chunk IDs.
  - `HITLTask`: Pending human approval records with payload snapshots, approver ID, and resolution status.
  - `SecurityAuditEvent`: Immutable security logs recording prompt injection attempts, tool violations, and unauthorized queries.

### 5. How Does It Scale?
- **Aurora Serverless v2**: Adjusts ACUs (Aurora Capacity Units) dynamically in increments of 0.5 ACUs without disrupting client connections.
- **Read / Write Splitting**: Analytical reporting queries target the Aurora reader endpoint, leaving the writer instance free for transactional state updates.
- **RDS Proxy**: Pools thousands of transient client connections into a controlled set of ~200 backend PostgreSQL connections.

### 6. What Happens When It Fails?
- **Aurora Multi-AZ Failover**: If the primary writer fails, Aurora promotes the read replica to writer in <30 seconds with zero data loss.
- **Redis Automatic Failover**: ElastiCache detects master node failure and promotes a read replica automatically in <15 seconds.

### 7. How Is It Secured?
- **Storage Encryption**: Encrypted at rest using AWS KMS Customer Managed Keys.
- **Transit Encryption**: SSL/TLS enforced on all connections (`rds.force_ssl = 1` in parameter groups, `rediss://` for Redis).
- **Network Isolation**: Placed in isolated private data subnets with no public internet ingress; only accessible by ECS security groups.

### 8. How Is It Monitored?
- Metrics: `RDS.CPUUtilization`, `RDS.ServerlessDatabaseCapacity`, `RDS.DatabaseConnections`, `ElastiCache.CPUUtilization`, `ElastiCache.Evictions`.
- Alarms: High CPU (>85%) and Redis evictions (>0) trigger P2 SRE warning notifications.

### 9. What Are the Trade-offs?
- **Aurora Serverless v2 Pricing**: ACU-hours cost more per GB of RAM than static provisioned RDS instances. However, the ability to scale down to 0.5–2.0 ACUs during weekends and off-market hours nets a ~40% overall cost reduction.

---

## 2. Spoken Interview Responses

### Interviewer: "Why did you include Redis in your architecture instead of doing everything in PostgreSQL?"
**Spoken Response:**
"Using PostgreSQL for everything sounds appealing on day one, but it breaks down rapidly under high-concurrency production load. We use Redis for three workloads where PostgreSQL is poorly suited:

1. **Sliding-Window Rate Limiting**: Our API limits users to specific requests per minute. If you record every API hit in PostgreSQL, you are executing thousands of `INSERT` and `DELETE` queries per second on a relational table. This generates massive write amplification and table bloat. In Redis, a sliding-window rate limit is executed as an atomic `ZADD` and `ZCARD` in RAM in under 0.5ms.
2. **LangGraph State Checkpointing**: As agents loop through research and tool calls, they update state multiple times per request. Writing complete intermediate state payloads to PostgreSQL disk tables introduces disk I/O latency. Redis stores these active state checkpoints in memory with a 24-hour TTL.
3. **Semantic AI Completion Caching**: When multiple analysts query identical SEC filing metrics, the AI Gateway checks Redis for a cached response using prompt hashes. Redis delivers the cached response in 2ms, saving hundreds of dollars in LLM API fees and eliminating database load entirely."

### Interviewer: "How do you prevent connection pool exhaustion as your application containers scale out?"
**Spoken Response:**
"In an asynchronous microservice architecture, connection exhaustion is a classic failure mode. If we scale our ECS Fargate cluster to 50 containers, and each container maintains an internal connection pool of 20 connections, that's 1,000 direct database connections hitting PostgreSQL. Under high load, PostgreSQL spends more CPU managing connection thread contexts than executing queries, leading to `FATAL: too many connections`.

We solve this using **Two Architectural Safeguards**:
1. **Asynchronous Connection Pooling in Python**: In `src/infrastructure/database.py`, we configure our SQLAlchemy async engine with `pool_size=20`, `max_overflow=10`, and `pool_pre_ping=True`. Connections are checked out only during active query execution and immediately returned to the pool using Python's async context manager (`async with get_db_session()`).
2. **AWS RDS Proxy in Production**: In our production Terraform manifests, all application traffic routes through AWS RDS Proxy. RDS Proxy holds thousands of incoming client connections open and multiplexes them across a small, highly optimized pool of ~200 backend PostgreSQL connections. When a container idles, RDS Proxy reclaims the backend connection and shares it with active containers, completely eliminating database connection starvation."
