# Enterprise Financial Research & Risk Copilot — Disaster Recovery & High Availability

## 1. SLA, RTO, and RPO Targets

The platform is designed to guarantee **99.99% system availability** for global financial institutions operating in continuous market environments.

| Metric | Target Specification | Architectural Mechanism |
| :--- | :--- | :--- |
| **Availability SLA** | **99.99%** | Multi-AZ active/active deployment across 3 AWS Availability Zones |
| **Recovery Point Objective (RPO)** | **< 1 minute** (Relational) / **0 seconds** (Audit Logs) | Aurora storage replication across 6 storage nodes + S3 Cross-Region Replication |
| **Recovery Time Objective (RTO)** | **< 30 seconds** (AZ failure) / **< 15 minutes** (Regional disaster) | Automated multi-AZ failover + Route 53 DNS failover to Warm Standby region |

---

## 2. Multi-AZ Active/Active High Availability Topology

```
AWS REGION PRIMARY (us-east-1)
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      Route 53 Latency-Based Health Routed Ingress                │
└──────────────────────────────────────────────────────────────────────────────────┘
            │                                 │                                 │
     AZ-1 (us-east-1a)                 AZ-2 (us-east-1b)                 AZ-3 (us-east-1c)
┌─────────────────────────┐       ┌─────────────────────────┐       ┌─────────────────────────┐
│ ALB Subnet 1            │       │ ALB Subnet 2            │       │ ALB Subnet 3            │
│ ECS Tasks (8-14 tasks)  │       │ ECS Tasks (8-14 tasks)  │       │ ECS Tasks (8-14 tasks)  │
│ OpenSearch (8 Data Nodes)│       │ OpenSearch (8 Data Nodes)│       │ OpenSearch (8 Data Nodes)│
│ OpenSearch Manager 1    │       │ OpenSearch Manager 2    │       │ OpenSearch Manager 3    │
│ ElastiCache Primary     │       │ ElastiCache Replica 1   │       │ ElastiCache Replica 2   │
│ Aurora Master DB        │       │ Aurora Replica 1        │       │ Aurora Replica 2        │
│ MSK Broker 1            │       │ MSK Broker 2            │       │ MSK Broker 3            │
└─────────────────────────┘       └─────────────────────────┘       └─────────────────────────┘
```

---

## 3. Component Failure Modes & Self-Healing Mechanisms

### 3.1 Amazon Aurora PostgreSQL Multi-AZ Failover
- **Failure Scenario**: Primary database instance hardware crash or AZ network partition.
- **Automated Failover Mechanism**:
  1. Aurora's distributed storage layer (6 copies across 3 AZs) maintains data availability without loss (RPO = 0).
  2. Aurora detects primary loss within 10–15 seconds via cluster heartbeat.
  3. Promotes an existing read replica in AZ-2 or AZ-3 to become the new primary writer.
  4. Amazon RDS Proxy transparently buffers inflight application transactions, shielding the FastAPI fleet from connection reset crashes.
  5. Total failover time: **< 30 seconds**.

### 3.2 Amazon OpenSearch Shard & Node Self-Healing
- **Failure Scenario**: Sudden termination of 1 or 2 OpenSearch data nodes.
- **Automated Recovery**:
  1. Each of the 200 primary shards has an identical replica shard located on a different node in a separate AZ.
  2. The cluster manager immediately promotes replica shards on healthy nodes to primary status (zero search downtime).
  3. AWS Auto Scaling launches replacement `r6g.4xlarge.search` data node instances.
  4. OpenSearch initiates background peer shard recovery to restore the desired 200 primary + 200 replica shard balance.

### 3.3 Amazon ElastiCache Redis Cluster Node Failure
- **Failure Scenario**: Primary Redis shard node failure.
- **Automated Recovery**:
  1. Redis Multi-AZ with Auto-Failover detects master failure via sentinel consensus within 15 seconds.
  2. Promotes the read replica in AZ-2 to primary.
  3. The FastAPI Redis client updates cluster topology dynamically without application restart.

### 3.4 AWS Bedrock Regional Quota Exhaustion or Outage
- **Failure Scenario**: AWS Bedrock in `us-east-1` experiences elevated 5xx error rates or regional quota throttling.
- **Automated Failover**:
  1. The Centralized AI Gateway circuit breaker trips after 5 consecutive failures.
  2. Automatically fails over model invocation to secondary Bedrock regional endpoints (`us-west-2` or `eu-central-1`).
  3. If Claude 3.5 Sonnet is unavailable, gracefully degrades to Claude 3.5 Haiku or cached semantic responses.

---

## 4. Multi-Region Disaster Recovery Strategy (Active/Passive Warm Standby)

For catastrophic regional outages affecting the primary AWS region (`us-east-1`):
1. **Secondary Region (`us-west-2`)**:
   - Aurora Global Database continuously replicates transactional storage asynchronously with lag $< 1$ second.
   - S3 Cross-Region Replication (CRR) replicates raw documents and chunk snapshots with KMS multi-region keys.
   - Minimal baseline compute fleet (4 ECS tasks, minimal OpenSearch cluster) runs continuously as a warm standby.
2. **Automated Regional Cutover**:
   - Route 53 health checks detect complete regional failure if all 3 AZ ALB probes fail for 3 consecutive checks (45 seconds).
   - Route 53 updates DNS records to route global traffic to `us-west-2`.
   - Auto Scaling policies in `us-west-2` scale ECS and OpenSearch to full production capacity within 10 minutes.
   - Total Regional RTO: **< 15 minutes**; RPO: **< 1 second**.

---

## 5. Backup, Snapshot & Restore Verification

- **Aurora PostgreSQL**: Continuous incremental backups with 35-day Point-in-Time Recovery (PITR). Automated daily full cluster snapshots replicated to secondary AWS region.
- **OpenSearch**: Automated hourly cluster snapshots to dedicated S3 bucket via OpenSearch Snapshot Management (SM).
- **Chaos Engineering Drills**: Quarterly GameDay simulation executing automated AZ failover, database primary termination, and synthetic poison pill injection.
