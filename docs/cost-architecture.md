# Enterprise Financial Research & Risk Copilot — Cost Architecture & FinOps

## 1. Executive Cost Model & FinOps Framework

At target scale (10M registered users, 100K peak CCU, 10,000 API RPS, 500–1,000 AI requests/sec, and 1B+ chunks), operating expenses must be rigorously governed via **Unit Economics** and **FinOps Cost Attribution**.

### Cost Attribution per Institutional Tenant
- Every AWS Bedrock token and OpenSearch query carries the authenticated `tenant_id` tag.
- Costs are attributed to tenants in real time, enabling tier-based margin analysis (e.g. 75%+ gross margin target on Enterprise client subscriptions).

---

## 2. Monthly Infrastructure Cost Sizing (Production Scale)

*Estimates based on US-East-1 AWS list prices with 3-Year Compute Savings Plans & Reserved Instances.*

| Infrastructure Component | Sizing & Configuration | Estimated Monthly Cost (On-Demand) | Optimized Monthly Cost (Savings Plan / RI) |
| :--- | :--- | :--- | :--- |
| **Amazon OpenSearch Service** | 24x `r6g.4xlarge.search` Data Nodes + 3x `c6g.xlarge.search` Managers + 36 TB gp3 EBS | $31,500 | **$18,900** (-40% 3-Yr RI) |
| **AWS ECS Compute (API Fleet)** | 30x average Fargate tasks (2 vCPU, 4 GiB RAM) | $4,300 | **$2,800** (-35% Compute SP) |
| **AWS ECS (Ingestion Workers)** | 16x average Fargate / EC2 tasks | $2,400 | **$1,550** (-35% Compute SP) |
| **Amazon Aurora PostgreSQL** | Multi-AZ Primary + 2 Read Replicas (`db.r6g.4xlarge`, 500 GB storage) | $5,800 | **$3,600** (-38% Database RI) |
| **Amazon ElastiCache Redis** | 3 Shards $\times$ 2 Nodes (6x `cache.r6g.large`, Multi-AZ) | $1,650 | **$1,050** (-36% ElastiCache RI) |
| **Amazon MSK (Kafka)** | 3x `kafka.m5.2xlarge` Brokers (3 AZs, 6 TB storage) | $2,100 | **$1,400** (-33% Savings) |
| **Amazon S3 & S3 Glacier** | 25 TB S3 Standard + 50 TB Glacier Archive + Object Lock | $850 | **$650** (Intelligent Tiering) |
| **Edge Ingress (CloudFront/WAF/ALB)**| 10K RPS Ingress, AWS WAF rules, ALB rule evaluations | $3,400 | **$2,800** |
| **AWS Data Transfer Out** | ~50 TB/month Internet Egress via CloudFront | $2,200 | **$1,600** |
| **Observability (Prometheus/CloudWatch)**| Logs, metrics, and trace ingestion | $1,800 | **$1,400** |
| **Subtotal Base Infrastructure** | - | **$56,000** | **$35,750 / month** |

---

## 3. Foundation Model Token Economics (AWS Bedrock)

### 3.1 AI Workload Volume & Traffic Mitigation
- Peak load: 1,000 AI req/s; Steady daytime average: 150 AI req/s.
- Daily AI queries: $\approx 150\text{ req/s} \times 86,400\text{ s} \approx 13,000,000\text{ queries/day}$.

### 3.2 Caching & Routing Cost Savings Multiplier
Without caching and query routing, transmitting 13M queries directly to Claude 3.5 Sonnet would cost **$180,000+ per day**. The 4-tier traffic absorber radically slashes this cost:

```
Total Daily Queries: 13,000,000
    ├── 35% Absorbed by Redis Semantic Cache: 4,550,000 queries ($0.00 model cost)
    └── 65% Evaluated by AI Gateway: 8,450,000 queries
          ├── 70% Routed to Fast Model (Claude 3.5 Haiku): 5,915,000 queries
          │   Input: 1,200 tokens @ $0.25/M = $1.77k/day
          │   Output: 400 tokens @ $1.25/M = $2.95k/day  ──► Subtotal: $4,720 / day
          └── 30% Routed to Deep Model (Claude 3.5 Sonnet): 2,535,000 queries
              Input: 3,500 tokens @ $3.00/M = $26.6k/day
              Output: 1,000 tokens @ $15.00/M = $38.0k/day ──► Subtotal: $64,600 / day
```

- **Provisioned Throughput (PT) Commitment**:
  - Purchasing 1-year Bedrock Provisioned Throughput units for baseline workload yields an additional **45% discount** over on-demand rates.
- **Titan Embeddings Cost**:
  - 100M document initial embedding (1B chunks $\times$ 500 tokens = 500B tokens @ $0.02/M) = **$10,000 one-time initial embedding cost**.
  - Daily steady-state ingestion (2.5M chunks/day $\times$ 500 tokens = 1.25B tokens @ $0.02/M) = **$25.00 / day ($750 / month)**.

---

## 4. Key Cost Optimization Levers

1. **Semantic Cache Hit Ratio (>0.96 Cosine)**:
   - Each 1% increase in semantic cache hit rate saves institutional tenants approximately **$1,900 / day ($57,000 / month)** in raw LLM token fees.
2. **OpenSearch UltraWarm & Cold Tiering**:
   - Filings older than 3 years migrate from NVMe/gp3 to S3-backed UltraWarm storage, reducing data node storage costs from $0.12/GB-month to $0.024/GB-month (an **80% storage cost reduction** for historical filings).
3. **Compute & Database Savings Plans**:
   - Committing to 3-year All-Upfront or Partial-Upfront Savings Plans for ECS Fargate, Aurora PostgreSQL, and OpenSearch yields **$20,250 / month in guaranteed infrastructure savings**.
