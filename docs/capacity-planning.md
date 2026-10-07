# Enterprise Financial Research & Risk Copilot — Capacity Planning & Sizing Model

## 1. Executive Capacity Summary & Workload Metrics

The capacity model is engineered to support an institutional global financial enterprise with high-burst trading hours and quarterly earnings seasons.

| Dimension | Specification | Architecture Sizing Baseline |
| :--- | :--- | :--- |
| **Registered Users** | 10,000,000 (10M) | Aurora PostgreSQL partitioned user tables + Cognito/Okta SSO |
| **Monthly Active Users (MAU)** | 2,000,000 (2M) | Active tenant directory and credential state |
| **Daily Active Users (DAU)** | ~500,000 (500K) | ~25% of MAU active during standard business days |
| **Peak Concurrent Users (CCU)** | 100,000 (100K) | Distributed Redis session state + async FastAPI connections |
| **Peak API Requests/sec (RPS)** | 10,000 RPS | AWS ALB + 24–40 ECS Tasks + Redis token bucket rate limiting |
| **Average API Requests/sec** | 2,500 RPS | Baseline load outside peak US/EU market hours |
| **Peak AI Requests/sec** | 500 – 1,000 req/s | Redis Semantic Cache (35% hit) + Tiered Claude 3.5 Haiku/Sonnet |
| **Average AI Requests/sec** | 150 req/s | Daytime research & compliance query load |
| **Document Corpus** | 100,000,000+ (100M+) | S3 Standard/Intelligent-Tiering with SSE-KMS |
| **Searchable Vector Chunks** | 1,000,000,000+ (1B+) | OpenSearch 2.x cluster (24 Data Nodes, 200 primary shards) |
| **Ingestion Throughput** | 50 docs/s peak (500 chunks/s) | Apache Kafka / MSK cluster + distributed chunking workers |
| **Availability SLA** | 99.99% | Multi-AZ active/active with automated failover |

---

## 2. Detailed Mathematical Sizing Calculations

### 2.1 User Base & Concurrency Sizing
- **Total Registered**: $10,000,000$ accounts.
  - User record size in PostgreSQL: ~1 KB (ID, email, hashed creds, role, tenant UUID, preferences).
  - Storage: $10^7 \times 1\text{ KB} = 10\text{ GB}$ (negligible relational footprint).
- **Peak Concurrent Users (CCU)**: $100,000$ active browser/terminal sessions.
  - Session state per CCU (JWT claim cache, active conversation pointer, permissions): ~4 KB in Redis.
  - Active session cache RAM: $100,000 \times 4\text{ KB} = 400\text{ MB}$.
  - TCP connection overhead on Load Balancers: 100K open TLS connections handled seamlessly by AWS Application Load Balancer with HTTP/2 multiplexing.

### 2.2 API Throughput & Compute Capacity (10,000 Peak API RPS)
- **Workload Breakdown**:
  - $85\%$ Read / Metadata / Status / Cache queries ($8,500\text{ RPS}$): Mean latency $20\text{ ms}$.
  - $10\%$ Relational Writes / Mutations / Portfolio Updates ($1,000\text{ RPS}$): Mean latency $60\text{ ms}$.
  - $5\%$ AI Invocations / Agent Reasoning ($500\text{ RPS}$ peak burst): Mean latency $1.2\text{ s}$ (streamed).
- **FastAPI Container Sizing**:
  - Benchmarked async I/O capacity per container (2 vCPU, 4 GiB RAM on AWS ECS Fargate or EC2 `c6g.xlarge`): ~600 RPS with `uvloop`.
  - Required container instances:
    $$\text{Target Tasks} = \frac{10,000\text{ RPS}}{600\text{ RPS/task}} \approx 16.7 \implies 20\text{ baseline tasks}$$
  - Sizing for $N+2$ high availability and multi-AZ resilience: **24 minimum tasks, auto-scaling up to 40 tasks** at 60% CPU utilization threshold.

### 2.3 AI Request Throughput (500 – 1,000 Peak AI req/s)
Directly transmitting 1,000 req/s to foundation models would incur prohibitive API costs (~$25,000+/hour) and trigger AWS Bedrock quota limits. The platform deploys a multi-tier traffic mitigation funnel:

```
[1,000 Peak AI Requests/sec]
          │
          ▼
┌───────────────────────────────────────────────┐
│  Tier 0: Redis Semantic Cache (>0.96 Cosine)  │  --> 35% Cache Hit (350 req/s absorbed)
└───────────────────────────────────────────────┘      Latency: ~15ms | Cost: $0.00
          │  (650 req/s cache miss)
          ▼
┌───────────────────────────────────────────────┐
│  Tier 1: Claude 3.5 Haiku (Router & Triage)   │  --> 65% of Misses (422.5 req/s)
└───────────────────────────────────────────────┘      Latency: ~250ms | Cost: Low
          │  (227.5 req/s complex reasoning)
          ▼
┌───────────────────────────────────────────────┐
│  Tier 2: Claude 3.5 Sonnet (Deep Memo Agent)  │  --> 35% of Misses (227.5 req/s)
└───────────────────────────────────────────────┘      Latency: ~1.5s - 3.5s (Streamed)
```

- **Bedrock Token Throughput Estimate**:
  - Tier 1 (Haiku): 422 req/s $\times$ 1,200 avg tokens/req = ~506,400 tokens/sec.
  - Tier 2 (Sonnet): 228 req/s $\times$ 3,500 avg tokens/req = ~798,000 tokens/sec.
  - Mitigated via AWS Bedrock **Provisioned Throughput (PT)** units for baseline load + On-Demand burst units.

---

## 3. Storage Sizing & OpenSearch Cluster Topology (1B+ Chunks)

### 3.1 Document Corpus & Chunk Multipliers
- **Total Documents**: $100,000,000$ (10-K, 10-Q, 8-K, transcripts, reports).
- **Average Chunks per Document**: 10 chunks (hierarchical financial chunking, 500 tokens/chunk).
- **Total Searchable Chunks**: $100,000,000 \times 10 = \mathbf{1,000,000,000\text{ (1 Billion Chunks)}}$.

### 3.2 Chunk Storage Footprint
1. **Raw Text Content**: 500 tokens $\approx$ 2,000 characters $\approx$ $2\text{ KB}$ text.
2. **Dense Vector Embedding**: 1,536 dimensions (float32 $\times$ 4 bytes) = $6,144\text{ bytes} \approx 6.14\text{ KB}$.
3. **Metadata**: Tenant ID, Doc ID, Ticker, Section, Date, CIK = $1.86\text{ KB}$.
4. **Index Structures**: Inverted BM25 index + HNSW graph adjacency lists = $2\text{ KB}$.
5. **Total Storage per Chunk**:
   $$\text{Storage/Chunk} = 2 + 6.14 + 1.86 + 2 = \mathbf{12\text{ KB per chunk}}$$

### 3.3 OpenSearch Disk & RAM Capacity Planning
- **Primary Data Size**:
  $$\text{Primary Data} = 10^9 \text{ chunks} \times 12\text{ KB} = 12,000,000,000\text{ KB} = \mathbf{12\text{ TB}}$$
- **Replication (1 Primary + 1 Replica)**:
  $$\text{Replicated Storage} = 12\text{ TB} \times 2 = \mathbf{24\text{ TB}}$$
- **Operating Watermark Buffer**: OpenSearch enforces flood-stage watermarks at 85% disk usage. Adding 25% growth and snapshot buffer:
  $$\text{Allocated Disk Capacity} = \frac{24\text{ TB}}{0.75} = \mathbf{32\text{ TB NVMe / gp3 EBS}}$$
- **RAM Sizing for k-NN HNSW Graphs**:
  - HNSW graph vectors require memory residency for sub-50ms search latency.
  - Compressed vectors (FP16 or Scalar Quantization to int8) reduce vector RAM footprint to ~1.54 KB per vector:
    $$\text{Vector RAM Required} = 10^9 \times 1.54\text{ KB} \approx 1.54\text{ TB RAM across cluster}$$
  - OpenSearch JVM Heap vs. OS Page Cache: 50% RAM to JVM heap (max 31 GiB per node), 50% to OS page cache for off-heap vector graphs.

### 3.4 OpenSearch Node Topology
- **Instance Type**: `r6g.4xlarge.search` (16 vCPU, 128 GiB RAM, up to 3 TB EBS gp3 storage).
- **Cluster Node Count**:
  - **Data Nodes**: **24 Data Nodes** across 3 Availability Zones (8 nodes/AZ).
    - Total Cluster RAM: $24 \times 128\text{ GiB} = \mathbf{3,072\text{ GiB (3.07 TB RAM)}}$ (exceeds the 1.54 TB graph requirement).
    - Total Storage: $24 \times 1.5\text{ TB gp3} = \mathbf{36\text{ TB Storage}}$.
  - **Cluster Manager Nodes**: **3 Dedicated Nodes** (`c6g.xlarge.search`) for cluster quorum and state management.
- **Shard Allocation**:
  - Primary Shards: 200 primary shards.
  - Replica Shards: 200 replica shards (total 400 shards).
  - Shard Size: $\frac{12\text{ TB}}{200} = \mathbf{60\text{ GB per shard}}$ (strictly within the optimal 30–65 GB/shard industry standard).

---

## 4. Ingestion Pipeline Throughput

- **Historical Ingestion**: 100M documents backfill executed over 14 days:
  $$\text{Historical Rate} = \frac{100,000,000\text{ docs}}{14 \times 86,400\text{ s}} \approx \mathbf{82.6\text{ docs/sec (826 chunks/sec)}}$$
- **Daily Steady-State Ingestion**:
  - ~250,000 new/updated filings, transcripts, and reports per business day.
  - Normal Rate: $\approx 5\text{ docs/sec}$.
  - Peak Burst Ingestion (e.g., 8:00 AM – 9:00 AM EST during earnings season): **50 docs/sec (500 chunks/sec)**.
- **Kafka MSK Ingestion Topic Partitioning**:
  - Topic: `financial-document-ingestion-v1`.
  - Partitions: 32 partitions (handles up to 2,000 msgs/sec per topic without lag).
  - Retention: 7 days with S3 tiered storage archival.

---

## 5. Bandwidth & Network Sizing

### 5.1 Ingress Bandwidth
- **Client API Ingress**: 10,000 RPS $\times$ 2 KB average payload = $20\text{ MB/s} = \mathbf{160\text{ Mbps}}$.
- **Document Ingestion Ingress**: 50 docs/s $\times$ 250 KB average raw file = $12.5\text{ MB/s} = \mathbf{100\text{ Mbps}}$.
- **Total Peak Ingress**: $\approx \mathbf{260\text{ Mbps}}$ (well within AWS 10 Gbps Direct Connect / Internet Gateway pipe).

### 5.2 Egress Bandwidth
- **Client API Egress**:
  - 85% metadata/read responses @ 4 KB = $8,500 \times 4\text{ KB} = 34\text{ MB/s}$.
  - 15% streaming AI answers @ 25 KB cumulative = $1,500 \times 25\text{ KB} = 37.5\text{ MB/s}$.
  - Total Client Egress: $71.5\text{ MB/s} = \mathbf{572\text{ Mbps}}$ (Peak burst ~1 Gbps).

### 5.3 Internal Service Mesh Bandwidth
- Application to OpenSearch: 1,000 retrieval RPS $\times$ 50 KB raw hits = $50\text{ MB/s} = 400\text{ Mbps}$.
- Application to Bedrock: ~1,500 Mbps.
- Total internal cluster bandwidth: $\approx \mathbf{2.5\text{ Gbps}}$ (serviced via 25 Gbps AWS ENA network interfaces).

---

## 6. Cache Sizing (Amazon ElastiCache Redis Cluster)

| Cache Component | Item Count | Avg Size | Total RAM | Eviction Policy | TTL |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Session & JWT Tokens** | 100,000 CCU | 4 KB | 400 MB | volatile-lru | 15 mins (sliding) |
| **Rate Limit Buckets** | 10,000,000 keys | 256 bytes | 2.56 GB | volatile-lru | 60 seconds |
| **Semantic AI Cache** | 250,000 entries | 14.1 KB (vec + text) | 3.52 GB | allkeys-lru | 24 hours |
| **Financial Quote Cache** | 15,000 tickers | 1 KB | 15 MB | volatile-lru | 60 seconds |
| **LangGraph Checkpoint State**| 25,000 active threads | 32 KB | 800 MB | volatile-lru | 7 days |
| **Operational Overhead** | Redis internals | - | 2.5 GB | - | - |
| **Total Redis RAM** | - | - | **~9.8 GB** | - | - |

- **Cluster Topology**: **3-Shard Primary Cluster with 3 Replicas** (6 nodes total) using `cache.r6g.large` (13.07 GiB RAM per node), providing 39.2 GiB total cluster memory across 3 AZs.
