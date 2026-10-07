# ADR-002: PostgreSQL (Amazon Aurora) with Row-Level Security (RLS) for Multi-Tenancy

## Status
Accepted

## Context
Serving 10 million registered users across thousands of enterprise financial tenants (banks, hedge funds, sovereign wealth funds) requires strict relational data isolation. Financial regulations (SEC, FINRA, GDPR, SOC 2 Type II) prohibit cross-tenant data leakage.

---

## Technical Evaluation (The 9 Architectural Dimensions)

### 1. Why this technology?
PostgreSQL provides enterprise-grade ACID transaction guarantees, rich JSONB semi-structured storage, and engine-level **Row-Level Security (RLS)**. RLS enforces tenant isolation within the database engine kernel rather than relying on application-layer `WHERE` clauses, preventing human error from leaking sensitive financial records. Amazon Aurora PostgreSQL adds a cloud-native storage engine replicating across 6 storage nodes in 3 Availability Zones with sub-30 second failover.

### 2. What alternatives were considered?
- **Database-per-Tenant (Isolated RDS instances per institution)**
- **Schema-per-Tenant (Separate PostgreSQL schema per institution in shared DB)**
- **Application-Layer Filtering Only (`WHERE tenant_id = ?`)**
- **NoSQL / DynamoDB**

### 3. Why were they rejected?
- **Database-per-Tenant**: Unmaintainable at thousands of institutional clients. Connection pool fragmentation would exhaust RDS limits, and running thousands of separate RDS instances would cost millions of dollars annually.
- **Schema-per-Tenant**: Schema migrations (e.g. Alembic DDL upgrades) running across 10,000 schemas cause lock escalation, connection spikes, and migration failures.
- **Application-Layer Filtering Only**: Extremely vulnerable to regression bugs or developer omission. In financial compliance, a single missed `WHERE tenant_id` clause constitutes a catastrophic regulatory breach.
- **DynamoDB**: Lacks native Row-Level Security, lacks cross-table ACID joins for complex HITL review workflows, and lacks transactional foreign key integrity.

### 4. What happens at 10M users?
10 million user records consume ~10 GB of storage. Aurora PostgreSQL effortlessly scales to 128 TB. With B-tree indexes on `(tenant_id, email)` and `(tenant_id, user_id)`, query lookup times remain $< 2\text{ ms}$.

### 5. What happens if the component fails?
- Aurora Multi-AZ maintains 6 copies of data across 3 Availability Zones.
- If the primary writer crashes, Aurora automatically detects failure via heartbeat within 15 seconds, promotes a healthy read replica, and updates DNS.
- Amazon RDS Proxy sits between the FastAPI fleet and Aurora, holding inflight client queries in memory during failover so applications do not crash with broken connection errors. Total failover time: **< 30 seconds**.

### 6. How does it scale?
- **Writes**: Scaled vertically up to `db.r6g.16xlarge` (64 vCPUs, 512 GiB RAM).
- **Reads**: Scaled horizontally by adding up to 15 Aurora Auto Scaling Read Replicas across 3 AZs.
- **Connection Spikes**: Managed via Amazon RDS Proxy, multiplexing thousands of container connections into a compact pool of database connections.

### 7. What is the operational cost?
Multi-AZ Aurora PostgreSQL Primary (`db.r6g.4xlarge`) + 2 Read Replicas + 500 GB storage costs ~$3,600/month under 3-Year Reserved Instance pricing.

### 8. What is the AWS production equivalent?
**Amazon Aurora PostgreSQL Multi-AZ Cluster** with **Amazon RDS Proxy**.

### 9. What is the local-development equivalent?
Local PostgreSQL container via Docker Compose (`postgres:16-alpine`) or lightweight SQLite in-memory for unit tests.
