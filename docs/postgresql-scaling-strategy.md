# PostgreSQL Scaling Strategy: Enterprise Financial Data Platform

## 1. Executive Summary & Scale Objectives

The **Enterprise Financial Research & Risk Copilot** is designed to support institutional financial operations at tier-1 enterprise scale:

- **10 Million Registered Users** (2M Monthly Active Users).
- **100,000 Peak Concurrent Users**.
- **10,000 Peak API Requests/Second (RPS)** across synchronous REST/GraphQL endpoints.
- **500–1,000 Peak AI Agent Workflow Invocations/Second**.
- **100M+ Financial Documents** (10-K, 10-Q, 8-K filings, earnings transcripts, broker research).
- **1B+ Searchable Vector/Text Chunks** (stored in OpenSearch/S3, referenced transactionally in PostgreSQL).
- **99.99% Availability Target** (< 52.6 minutes annual downtime).
- **SEC Rule 17a-4 & FINRA Compliance** (immutable 7-year audit retention, WORM compliance).

This document establishes the production scaling architecture for the transactional PostgreSQL 16+ data layer, detailing indexing patterns, connection multiplexing, read/write segregation, declarative partitioning, cold archival pipelines, and high-performance query execution.

---

## 2. PostgreSQL Architectural Role & Workload Segregation

PostgreSQL serves as the **Single Source of Truth (SSOT)** for transactional, identity, and governance state. High-volume unstructured embeddings and document vectors are intentionally offloaded to OpenSearch and S3:

```
                      +---------------------------------------+
                      |       Enterprise API Gateway          |
                      |  10,000 RPS (FastAPI + Envoy Proxy)   |
                      +-------------------+-------------------+
                                          |
                +-------------------------+-------------------------+
                |                                                   |
      [Transaction Writes & Critical Reads]                [Unstructured Search]
                |                                                   |
      +---------v----------+                               +--------v---------+
      |  PgBouncer Cluster |                               | OpenSearch 2.11  |
      |  (Transaction Pool)|                               | (1B+ Embeddings) |
      +---------+----------+                               +------------------+
                |
       +--------+------------------------+
       |                                 |
+------v--------------+       +----------v----------+
|  Primary PostgreSQL | ----> | Read Replicas (x4)  |
|  (Writes & OCC)     | WAL   | (Queries & Reports) |
+---------------------+       +---------------------+
```

---

## 3. Indexing Strategy Analysis

Blindly indexing columns degrades write throughput and bloats memory caches. Our indexing strategy employs targeted B-Tree, Partial, Composite, and BRIN indexes aligned with our query access patterns.

### 3.1 Composite Indexes with Tenant Isolation Prefixing

Every enterprise query filters by `tenant_id`. Placing `tenant_id` as the leading column in composite indexes enables PostgreSQL B-Trees to isolate leaf pages directly to the tenant's data partition:

- **`idx_doc_tenant_ticker`** (`documents`): `(tenant_id, ticker, is_deleted)`
  - *Query Pattern*: `SELECT * FROM documents WHERE tenant_id = :t AND ticker = :sym AND is_deleted = FALSE`
  - *Index Type*: B-Tree.
- **`idx_holding_tenant_ticker`** (`holdings`): `(tenant_id, ticker)`
  - *Query Pattern*: Portfolio exposure aggregations across tickers for a given fund.
- **`idx_port_tenant_name`** (`portfolios`): `(tenant_id, name, is_deleted)`
  - *Query Pattern*: Case-insensitive or prefix matching for portfolio management desks.

### 3.2 Partial Indexes for Active & Unarchived Records

Soft deletion (`is_deleted = TRUE`) and archival flags (`is_archived = TRUE`) are standard in financial systems. Indexing tombstoned records wastes disk and buffer cache.

```sql
-- Partial index: only index non-deleted, active documents
CREATE INDEX idx_doc_active_lookup
ON documents (tenant_id, ticker, doc_type)
WHERE is_deleted = FALSE;

-- Partial index: only index unarchived, active conversation threads
CREATE INDEX idx_conv_active_threads
ON conversations (tenant_id, user_id, updated_at DESC)
WHERE is_deleted = FALSE AND is_archived = FALSE;
```

**Benefits**:
- Reduces index tree height by 30–50% on mature installations.
- Eliminates index maintenance overhead when soft-deleting documents or conversations.

### 3.3 BRIN (Block Range Index) for High-Velocity Append-Only Tables

The `audit_events`, `agent_runs`, and `tool_executions` tables ingest millions of rows per day in strict chronological order (`created_at`). 

A standard B-Tree index on 100M rows consumes **~2.2 GB** of memory. A **BRIN index** summarises ranges of physical disk pages (e.g. 128 pages per range), consuming **< 2 MB** (a 1,000x footprint reduction):

```sql
-- BRIN index on append-only audit event log
CREATE INDEX idx_audit_created_brin
ON audit_events USING BRIN (created_at)
WITH (pages_per_range = 128);

-- BRIN index on agent execution logs
CREATE INDEX idx_agent_run_created_brin
ON agent_runs USING BRIN (created_at)
WITH (pages_per_range = 64);
```

### 3.4 What We Do NOT Index in PostgreSQL

1. **Document Full-Text Body (`content`)**:
   - Storing 100M document texts in PostgreSQL `tsvector` columns induces severe vacuum bloat and massive WAL amplification.
   - Text search and semantic hybrid search are strictly delegated to **OpenSearch**.
2. **High-Cardinality JSON Blobs (`citations_json`, `positions_json`, `details_json`)**:
   - JSONB GIN indexes are avoided unless specific ad-hoc filtering is mandated by API contracts.

---

## 4. Connection Pooling Architecture

### 4.1 The 10,000 RPS Concurrency Challenge

A common antipattern is opening thousands of direct database connections from API pods. In PostgreSQL, each backend worker process:
- Consumes **8–12 MB** of physical RAM (plus `work_mem` allocations).
- Contends for PostgreSQL shared buffer spinlocks and CPU cache lines.
- Beyond 100–200 concurrent active PostgreSQL backends, query throughput degrades sharply due to OS context switching.

### 4.2 Sizing with Little's Law

By applying **Little's Law** ($L = \lambda \times W$):
- Target Throughput ($\lambda$): **10,000 API requests/second**.
- Average Database Query Time ($W$): **2.5 milliseconds** (0.0025s) with indexed lookups and in-memory buffer hits.
- Required Active Database Connections ($L$):
  $$L = 10,000 \times 0.0025 = 25 \text{ concurrent connections}$$

Factoring in a 3x safety margin for transaction spikes and complex multi-join rebalancing queries:
**80 to 120 physical database backend connections** are optimal to saturate 32-vCPU / 64-vCPU database instances without thrashing.

### 4.3 Two-Tier Pooling Architecture

```
+-----------------------------------------------------------+
| FastAPI Application Pods (50 Pods across Kubernetes)       |
| asyncpg Engine Pool: pool_size=20, max_overflow=10        |
| Total Client Sockets: 50 x 30 = 1,500 persistent sockets   |
+-----------------------------+-----------------------------+
                              |
                              v
+-----------------------------------------------------------+
| PgBouncer Sidecar / Cluster (Active-Active)                |
| Mode: TRANSACTION POOLING                                 |
| Client Sockets: 1,500 clients held open                   |
| Server Connections to PG Primary: 60 connections          |
| Server Connections to PG Replicas: 120 connections        |
+-----------------------------+-----------------------------+
                              |
                              v
+-----------------------------------------------------------+
| PostgreSQL Primary & Replicas (max_connections = 250)     |
| 60-120 active backends executing queries in <3ms          |
+-----------------------------------------------------------+
```

### 4.4 Transaction Pooling Guidelines

Because PgBouncer operates in `transaction` mode:
- Sockets are returned to the pool immediately upon `COMMIT` or `ROLLBACK`.
- Session-level state features (`LISTEN/NOTIFY`, `SET search_path`, session-level prepared statements without query named IDs) are prohibited.
- SQLAlchemy 2.x asyncpg connects cleanly with `statement_cache_size=0` or prepared statement names disabled in PgBouncer compatibility mode.

---

## 5. Read Replicas & CQRS Read/Write Splitting

### 5.1 Topology

To sustain 10K RPS where ~85% of traffic is read-intensive:
- **1 Primary DB (r6i.8xlarge, 32 vCPU, 256 GB RAM)**: Dedicated to mutations, optimistic locking updates, and ingestion pipelines.
- **4 Read Replicas (r6i.4xlarge, 16 vCPU, 128 GB RAM)**: Serving search queries, portfolio reports, risk dashboard queries, and conversation history.

### 5.2 Read-Your-Own-Writes Consistency (Mitigating Replication Lag)

Streaming replication introduces asynchronous replication lag (typically 5–50ms). To prevent users from experiencing stale reads immediately after updating a portfolio or sending a chat message:

1. **Mutation Timestamp Tagging in Redis**:
   - On write (`POST /api/v1/portfolios/{id}/rebalance`): The application writes to the Primary and stores a Redis key:
     `tenant:{tenant_id}:last_write = <current_timestamp>` with TTL = 2 seconds.
2. **Session Dependency Routing**:
   - When handling subsequent `GET` requests: If `now - last_write < 2.0s`, route query to the **Primary** instance.
   - Otherwise, route to the **Read Replica** pool.

---

## 6. Selective Table Partitioning Strategy

### 6.1 Architectural Rationale: Avoiding "Partitioning Everywhere"

Blindly partitioning every table (e.g. partitioning `users`, `roles`, or `portfolios`) introduces severe penalties:
- Sub-partition routing adds CPU planning overhead to sub-millisecond queries.
- Global foreign keys and unique constraints across non-partitioned tables become restricted or require composite partition keys.
- Small tables (< 5M rows) fit entirely in RAM buffer caches (`shared_buffers`); partitioning them fragments cache lines with zero gain.

### 6.2 Partition Decision Matrix

| Entity | Est. Annual Rows | Partitioned? | Partition Key | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **`AuditEvent`** | 1.5 Billion | **YES** | `RANGE (created_at)` | Append-only audit trail; monthly partitions allow instant drop/detach for cold archive. |
| **`AgentRun`** | 150 Million | **YES** | `RANGE (created_at)` | Reasoning traces age out; high write velocity; monthly partitions. |
| **`ToolExecution`**| 450 Million | **YES** | `RANGE (created_at)` | Sub-agent step logs; monthly range partitioning aligned with `AgentRun`. |
| **`Tenant`** | 5,000 | **NO** | — | Pure reference table; 100% in-memory buffer cached. |
| **`User`** | 10 Million | **NO** | — | Indexed by `email` and `id`; partition routing would hurt auth token validation latency. |
| **`Role` / `Permission`**| < 1,000 | **NO** | — | Static RBAC catalogs; fully cached in Redis & PostgreSQL RAM. |
| **`Portfolio`** | 500,000 | **NO** | — | Low volume; sub-second mutation via Optimistic Concurrency Control (`version`). |
| **`Holding`** | 25 Million | **NO** | — | Scoped by `portfolio_id`; fast B-Tree index scan (< 1ms). |
| **`Document`** | 100 Million | **NO** | — | Catalog records (< 50 GB data size); chunks are in OpenSearch. B-Tree index on `(tenant_id, ticker)` suffices. |
| **`Conversation`** | 50 Million | **NO** | — | Scoped to `(tenant_id, user_id)`. Soft-deleted / archived via partial index. |

### 6.3 Declarative Range Partitioning Implementation

```sql
-- Partitioned Audit Events Table
CREATE TABLE audit_events (
    id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    tenant_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36),
    event_type VARCHAR(100) NOT NULL,
    action_status VARCHAR(20) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id VARCHAR(255),
    ip_address VARCHAR(45),
    details_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- Monthly Partitions (automated via pg_partman or cron worker)
CREATE TABLE audit_events_y2026m10 PARTITION OF audit_events
    FOR VALUES FROM ('2026-10-01 00:00:00') TO ('2026-11-01 00:00:00');

CREATE TABLE audit_events_y2026m11 PARTITION OF audit_events
    FOR VALUES FROM ('2026-11-01 00:00:00') TO ('2026-12-01 00:00:00');
```

---

## 7. Archival & Retention Strategy (SEC 17a-4 / FINRA)

Institutional financial compliance requires storing audit logs and investment records for **7 years**, with immediate availability for the first 2 years:

```
[Hot Layer (PostgreSQL NVMe)]       0 - 90 Days    Active Querying (<5ms)
               |
               v (pg_partman detach)
[Warm Layer (PostgreSQL Read-Only)] 90 - 365 Days  Auditor Queries (<50ms)
               |
               v (AWS DMS / S3 Parquet Export)
[Cold Layer (Amazon S3 Glacier)]    1 - 7 Years    WORM Compliant (Object Lock)
               |
               v (Automated DDL Drop)
[PostgreSQL Table Drop]             > 365 Days     0-Second VACUUM / Zero Fragmentation
```

### 7.1 Automated Zero-Downtime Partition Detachment

When a monthly partition exceeds 365 days:
1. **Detach Partition**:
   ```sql
   ALTER TABLE audit_events DETACH PARTITION audit_events_y2025m10 CONCURRENTLY;
   ```
2. **Export to Parquet**: AWS Glue / DMS pipeline dumps the detached table to Amazon S3 in compressed Parquet format.
3. **Verify WORM Checksum**: Verify SHA-256 integrity hash against SEC 17a-4 compliance vault.
4. **Drop Detached Table**:
   ```sql
   DROP TABLE audit_events_y2025m10;
   ```
   *Result*: Terabytes of disk space reclaimed in **0 milliseconds** with **zero autovacuum lock contention**.

---

## 8. High-Performance Query Patterns & Concurrency Control

### 8.1 Keyset (Cursor-Based) Pagination vs OFFSET Bloat

For 100M+ documents and conversation histories, standard `OFFSET 100000 LIMIT 50` requires scanning and discarding 100,000 rows on every query, generating quadratic I/O load.

Our repository framework utilizes **Deterministic Keyset Pagination**:

```sql
-- Keyset pagination query pattern
SELECT id, title, ticker, doc_type, created_at
FROM documents
WHERE tenant_id = :tenant_id
  AND is_deleted = FALSE
  AND (created_at, id) < (:cursor_created_at, :cursor_id)
ORDER BY created_at DESC, id DESC
LIMIT :page_size;
```

*Execution Complexity*: $O(\log N)$ B-Tree index descent regardless of how deep the client paginates.

### 8.2 Optimistic Concurrency Control (OCC) for Financial State

To protect portfolios from race conditions during concurrent rebalancing without blocking reads using heavyweight `SELECT FOR UPDATE` locks:

```sql
UPDATE portfolios
SET total_value = :new_value,
    positions_json = :new_positions,
    version = version + 1,
    updated_at = NOW()
WHERE id = :portfolio_id
  AND tenant_id = :tenant_id
  AND version = :expected_version
  AND is_deleted = FALSE;
```

If `rowcount == 0`:
- Another risk officer or trading process committed an update concurrently.
- The service aborts cleanly and raises `OptimisticConcurrencyException` (HTTP 409 Conflict), allowing the client or agent graph to re-read and retry.

---

## 9. PostgreSQL Production Engine Configuration

Tuned for an **AWS RDS / Aurora PostgreSQL (r6i.8xlarge: 32 vCPU, 256 GB RAM)**:

```ini
# Memory Configuration
shared_buffers = 64GB                  # 25% of total system RAM
effective_cache_size = 192GB          # 75% of total RAM
maintenance_work_mem = 4GB            # Fast index creation and VACUUM
work_mem = 64MB                       # Sized for 100 concurrent complex sort/hash joins

# Checkpoint & WAL Tuning for High Write Ingestion
max_wal_size = 32GB
min_wal_size = 4GB
checkpoint_completion_target = 0.9    # Smooth out I/O spikes
checkpoint_timeout = 15min

# Storage & Query Planner Tuning
random_page_cost = 1.1                # Fast NVMe SSD EBS gp3 / io2
effective_io_concurrency = 200        # Highly concurrent SSD read capability

# Aggressive Autovacuum for High Ingestion Rates
autovacuum = on
autovacuum_max_workers = 6
autovacuum_vacuum_scale_factor = 0.05 # Trigger vacuum at 5% row churn (default 20% is too late)
autovacuum_vacuum_cost_limit = 2000   # Prevent autovacuum from throttling on fast NVMe
```
