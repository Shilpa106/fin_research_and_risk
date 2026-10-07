# ADR-004: Redis for Rate Limiting, Semantic Caching, and Session State

## Status
Accepted

## Context
At 10,000 peak API requests/second and 100,000 concurrent users, the platform requires sub-2ms in-memory data structures to handle:
1. High-throughput atomic token bucket rate limiting (protecting against burst exhaustion).
2. Semantic caching of AI responses (absorbing 35–45% of peak AI queries).
3. JWT session verification and refresh token invalidation.
4. Distributed locks and LangGraph checkpoint state caching.

---

## Technical Evaluation (The 9 Architectural Dimensions)

### 1. Why this technology?
Redis provides in-memory, single-threaded execution guarantees with sub-millisecond response times. It supports atomic Lua scripting (essential for evaluating token-bucket rate limits without race conditions), native hash data structures, and Redis Stack vector similarity search capabilities for semantic caching.

### 2. What alternatives were considered?
- **Memcached**
- **DynamoDB Accelerator (DAX)**
- **In-Memory Application Local Cache (e.g. Python dict / cachetools)**
- **Hazelcast / Apache Ignite**

### 3. Why were they rejected?
- **Memcached**: Lacks atomic Lua scripting, lacks vector search, and only supports simple key-value strings without data structures (hashes, sets, sorted sets).
- **DAX**: Strictly tied to DynamoDB; lacks Lua scripting and vector similarity search.
- **In-Memory Application Cache**: In a horizontally autoscaling fleet of 40+ container tasks, local caches cannot share rate limit counters or semantic query responses, resulting in burst leakage across tasks.
- **Hazelcast / Apache Ignite**: Significant operational complexity and heavyweight Java runtime requirements.

### 4. What happens at 10M users?
User sessions and rate limit keys expire automatically via aggressive TTL policies (60 seconds for rate limits, 15 minutes for sessions). Total active Redis RAM footprint remains under 10 GiB across the entire cluster.

### 5. What happens if the component fails?
- Amazon ElastiCache Redis operates in Multi-AZ with Auto-Failover. If the primary node crashes, replica promotion occurs within 15 seconds.
- In the event of a catastrophic complete Redis cluster loss, the FastAPI rate limiter is programmed to **fail open** (permits requests with fallback warning logging) to preserve 99.99% system availability while Redis restarts.

### 6. How does it scale?
Horizontally via Redis Cluster sharding (cluster mode enabled). Keys are automatically distributed across 16,384 hash slots. Shards can be dynamically added with zero downtime.

### 7. What is the operational cost?
3 Shards $\times$ 2 Nodes (6x `cache.r6g.large`, 39 GiB RAM across 3 AZs) costs ~$1,050/month under 3-Year Reserved Instances.

### 8. What is the AWS production equivalent?
**Amazon ElastiCache for Redis (Cluster Mode Enabled)** with Multi-AZ and Auto-Failover.

### 9. What is the local-development equivalent?
Local Redis container via Docker Compose (`redis:7.2-alpine`) on `localhost:6379`.
