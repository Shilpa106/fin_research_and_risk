# 16 — Master Guide: 23 Difficult Interviewer Follow-Up Questions

> **Interview Coaching Note**: All responses below are written in the **first-person spoken voice** of a Principal AI Architect defending the implemented system during a rigorous client or leadership interview. Avoid textbook recitations; speak directly to architectural rationale, actual implementation mechanics, and production realities.

---

### 1. Why LangGraph instead of LangChain?
**Spoken Response:**
"LangChain LCEL is fundamentally an acyclic pipeline—you go from input to prompt to model to output. But real financial research is inherently **cyclic**. An analyst queries a 10-K, realizes they're missing debt amortization tables, triggers a tool, inspects the result, and loops back to refine their research.

The old LangChain `AgentExecutor` supported loops, but it was an opaque black box. You couldn't persist state mid-loop, inspect transitions, or halt execution for three hours to get a compliance officer's sign-off. LangGraph turns that into an explicit, deterministic state-machine graph where every node transition is tracked, every state snapshot is persisted to Redis or PostgreSQL, and we can place an `interrupt_before` hook to pause execution for human approval without losing context."

---

### 2. Why hybrid search?
**Spoken Response:**
"Because in finance, neither pure semantic search nor pure keyword search works on its own. 

Dense embeddings are fantastic for conceptual questions like *'What are the macro interest rate vulnerabilities?'* where the text says *'monetary policy exposure'*. But dense embeddings fail catastrophically on exact financial tokens like *'Item 1A Form 10-K'*, *'FY2023 EBITDA'*, or *'Section 4.02 Credit Agreement'*. BM25, on the other hand, excels at exact string matching but fails on synonyms. 

By combining dense k-NN search and sparse BM25 via Reciprocal Rank Fusion (RRF), we get the best of both worlds: exact numerical and covenant matching paired with conceptual semantic understanding."

---

### 3. Why OpenSearch?
**Spoken Response:**
"OpenSearch gives us native, production-grade hybrid search with built-in Reciprocal Rank Fusion out of the box. It manages inverted BM25 indices and high-dimensional vector graphs (HNSW) in a single distributed cluster. 

More importantly, it scales independently from our relational database. Ingesting millions of pages of SEC filings and corporate transcripts is an I/O and RAM-intensive workload; isolating it on dedicated OpenSearch data nodes with gp3 EBS volumes ensures search indexing never degrades our transactional PostgreSQL database."

---

### 4. Why not just use PostgreSQL pgvector?
**Spoken Response:**
"We evaluated `pgvector` during our early prototyping, and it failed for two primary reasons:
1. **Lack of True BM25 Hybrid Search**: PostgreSQL has `tsvector` for basic full-text search, but it lacks true BM25 probabilistic relevance scoring and has no native Reciprocal Rank Fusion algorithm.
2. **Buffer Pool Contention**: High-dimensional vector search on HNSW indexes is memory-hungry. Running large vector searches inside PostgreSQL rapidly evicts standard relational tables and B-tree indexes from shared memory, causing our transactional queries on users, auth, and audit logs to slow down drastically under load."

---

### 5. How do you prevent cross-tenant retrieval?
**Spoken Response:**
"We enforce tenant isolation at the query abstract syntax tree (AST) level in `src/rag/retrieval_service.py`. We never rely on the LLM or client frontend to pass the tenant filter.

When a request arrives, our `CorrelationIdMiddleware` extracts the authenticated `tenant_id` from the cryptographically verified JWT token claims. When the RAG engine compiles the OpenSearch DSL query, our `TenantBoundaryEnforcer` injects a mandatory `{'term': {'tenant_id': current_tenant_id}}` filter clause directly into the root boolean query. Even if a user attempts an adversarial prompt injection asking the model to retrieve documents from another firm, the search engine physically cannot return any chunk that doesn't match that tenant ID."

---

### 6. How does an agent choose an MCP tool?
**Spoken Response:**
"We use model-native structured tool calling via Anthropic Claude 3.5 Sonnet's `tools` API in AWS Bedrock. 

When an agent node activates, we only serialize the specific tools registered for that agent's role into the request payload. Each tool has a strict Pydantic schema specifying required arguments, types, and descriptions. The model analyzes the user query, determines which tool fits the requirement, and outputs a structured `tool_use` block containing the tool name and JSON parameters. Our MCP Gateway then validates that payload against the Pydantic schema before executing the tool."

---

### 7. How do you secure MCP?
**Spoken Response:**
"Every MCP tool invocation is treated as an untrusted remote execution request. We enforce a four-stage guardrail in `src/mcp/gateway.py`:
1. **RBAC Validation**: We check that the user's role has explicit permission to execute the requested tool.
2. **Schema Validation**: Arguments are validated against strict Pydantic schemas, enforcing boundaries and types.
3. **Malicious Input Scrubbing**: Parameters are scanned for SQL injection keywords, command injection metacharacters (`|;&`), and directory traversal attempts (`../`).
4. **Mandatory Tenant Context Injection**: The agent is not permitted to supply or override the `tenant_id` parameter; our gateway strips it and injects the authenticated `tenant_id` from the session context, preventing cross-tenant tool invocation."

---

### 8. How do you prevent prompt injection?
**Spoken Response:**
"We implement dual-sided defense:
1. **Input Sanitization**: Our `InputSanitizer` in `src/security/sanitizer.py` scans incoming user prompts using heuristic regex and keyword matchers for jailbreak signatures like *'ignore previous instructions'*, *'system override'*, and roleplay personas.
2. **Context Delimitation**: When retrieved document chunks are injected into the prompt, they are strictly enclosed in XML-escaped data tags: `<context id='123' untrusted='true'>...</context>`. The system prompt explicitly instructs the model to treat everything inside context tags purely as inert data and never as executable instructions.
3. **Privilege Separation**: Even if an injection bypassed the model, the agent possesses zero unvetted tool privileges. It cannot run arbitrary shell scripts or unverified database mutations."

---

### 9. How do you control LLM cost?
**Spoken Response:**
"Uncontrolled token costs will destroy the margins of an AI SaaS platform. We control costs at three layers in `src/ai_gateway/cost_tracker.py`:
1. **Pre-Flight Tenant Budgets**: Each tenant has a monthly dollar allocation stored in Redis. Before making an LLM call, the gateway verifies that the tenant hasn't exceeded their quota.
2. **Semantic Caching**: Identical or highly repetitive queries are cached in Redis using prompt hashes, returning cached responses in 3ms with zero LLM API cost.
3. **Micro-Cent Metering**: Every single API response extracts `prompt_tokens` and `completion_tokens`. We compute the exact cost based on model pricing tables, logging it to OpenTelemetry metrics and attaching it to the conversation record for client chargebacks."

---

### 10. How do you handle model failure?
**Spoken Response:**
"We implement an automated **Circuit Breaker and Fallback Chain** in `src/ai_gateway/circuit_breaker.py`. 

If our primary model (Claude 3.5 Sonnet on AWS Bedrock) encounters three consecutive timeouts (>10s) or HTTP 429 throttling errors within 30 seconds, the circuit trips to `OPEN`. The gateway instantly redirects subsequent requests to Claude 3.5 Haiku (or a secondary AWS region). Haiku handles the reasoning with slightly less nuance but at ten times the speed, keeping the platform available. After 60 seconds, the circuit enters `HALF_OPEN` to canary test the primary provider before switching back."

---

### 11. How do you handle 10M users?
**Spoken Response:**
"Ten million registered users is an architectural challenge of **statelessness and storage tiering**:
1. **Stateless RS256 Authentication**: User sessions are validated using public key cryptography in memory. Verifying a JWT token requires zero database hits.
2. **Database Partitioning**: Aurora PostgreSQL partitions high-volume tables (`conversation_messages`, `audit_logs`) by `tenant_id` and date range, preventing index degradation.
3. **S3 Storage Lifecycle**: Ingested financial filings are stored in S3, with lifecycle policies transitioning older documents to Glacier Flexible Retrieval, reducing storage costs by over 70%.
4. **CloudFront Global Edge**: Public filings and static assets are cached at AWS edge locations, absorbing read traffic before it touches our origin."

---

### 12. How would you scale to 100K concurrent users?
**Spoken Response:**
"In our real empirical load tests, we proved that **100,000 concurrent socket connections cannot run on a single machine** because the host OS dynamic TCP port table only has 16,384 ports (`netsh int ipv4 show dynamicport tcp`).

To scale to 100K concurrent users in production, we distribute load across AWS:
1. **Ingress**: AWS CloudFront terminates TLS globally; an Application Load Balancer terminates client HTTP/2 connections across 3 Availability Zones.
2. **Compute**: ECS Fargate auto-scales from 4 to **50 tasks** (100 vCPUs, 200 GiB RAM) based on target tracking of 1,000 requests per target.
3. **Database**: **AWS RDS Proxy** pools tens of thousands of container connections into ~200 backend PostgreSQL connections, while Aurora Serverless v2 scales up to 32 ACUs.
4. **In-Memory Caching**: Multi-AZ ElastiCache Redis cluster handles 100K+ ops/sec for rate limits and session validation in <1ms."

---

### 13. How do you evaluate hallucinations?
**Spoken Response:**
"We evaluate hallucinations using algorithmic **Faithfulness and Citation Grounding** in `src/evaluation/rag_evaluator.py`:
1. We decompose the generated answer into individual atomic factual statements.
2. We verify each statement against the retrieved source chunks provided in the prompt context.
3. We calculate `Faithfulness = Supported Claims / Total Claims`.
4. We verify that every cited chunk anchor exists in our database and matches the exact SHA256 content hash of the retrieved text. If an answer makes unsupported claims or cites non-existent chunks, our CI regression gate fails the build."

---

### 14. How do you evaluate agents?
**Spoken Response:**
"We evaluate agents across four objective dimensions in `src/evaluation/agent_evaluator.py`:
1. **Task Success**: Did the final response fulfill the prompt's intent?
2. **Tool Selection Accuracy**: At each trajectory step, did the agent select the expected tool from its allowlist?
3. **Trajectory Correctness**: Did the agent follow an optimal path, or did it waste tokens in redundant loops?
4. **Token & Latency Efficiency**: Did execution stay within latency SLAs and cost budgets? All evaluations run automatically against golden datasets in CI."

---

### 15. How do you handle a poisoned document?
**Spoken Response:**
"If a fraudulent or malicious document is uploaded:
1. **Ingestion Sanitization**: Our ingestion parser strips executable scripts, non-printable characters, and prompt injection signatures.
2. **Instant Quarantine**: An administrator can call `POST /api/v1/documents/{id}/quarantine`, which immediately sets the document status to `QUARANTINED` in PostgreSQL.
3. **Index Purge**: An asynchronous worker immediately purges all chunks associated with that `document_id` from the OpenSearch cluster.
4. **Audit Traceability**: Because every conversation stores the exact `chunk_ids` it referenced, we can run an immediate audit query to identify every user query that cited the poisoned document and issue automated corrections."

---

### 16. What happens when OpenSearch is unavailable?
**Spoken Response:**
"If OpenSearch is down, the retrieval service catches the connection error and checks Redis for a cached retrieval result. If there is a cache miss, the service returns an empty context with `retrieval_status: 'UNAVAILABLE'`. 

Our system prompt strictly forbids the model from guessing or fabricating financial metrics without source filings. The agent responds: *'The SEC filing retrieval subsystem is currently unavailable. To maintain compliance accuracy, I cannot calculate this metric without verified source filings.'* We prioritize zero hallucinations over an ungrounded guess."

---

### 17. What happens when Bedrock times out?
**Spoken Response:**
"Our AI Gateway wraps every model call in an explicit 10-second timeout. If AWS Bedrock hangs, the gateway catches the `TimeoutException`, increments the circuit breaker failure counter, and fails over immediately to Claude 3.5 Haiku or a secondary AWS region. The user receives their analysis without hanging indefinitely."

---

### 18. How do you prevent infinite agent loops?
**Spoken Response:**
"We enforce a triple-lock mechanism:
1. **Deterministic State Counter**: The LangGraph state maintains an immutable `iteration_count`. If it hits 10, conditional edge routing forces an immediate transition to the `synthesizer` node.
2. **Tool Repetition Detection**: Calling the exact same tool with identical parameters twice in a row triggers an exception, forcing the agent to alter its approach.
3. **Hard Timeout & Token Budget**: Runs are bounded by an `asyncio.wait_for(timeout=30.0)` wrapper and a maximum token expenditure cap."

---

### 19. Why use Redis?
**Spoken Response:**
"We use ElastiCache Redis for three workloads where PostgreSQL is inefficient:
1. **Sliding-Window Rate Limiting**: Executing thousands of atomic `ZADD`/`ZCARD` operations in memory in <0.5ms without relational table bloat.
2. **LangGraph State Checkpointing**: Storing active, in-flight multi-agent execution state in memory with 24-hour TTLs.
3. **Semantic AI Caching**: Serving identical financial filing queries from memory in <3ms, eliminating redundant Bedrock API costs."

---

### 20. Why use SQS?
**Spoken Response:**
"We use AWS SQS to decouple heavy, asynchronous workloads from the real-time API. Parsing a 500-page 10-K filing, computing vector embeddings, and indexing chunks takes 30–60 seconds. Doing that synchronously inside an HTTP request would cause gateway timeouts. 

With SQS:
- Ingestion tasks are queued instantly, returning an HTTP 202 Accepted to the user.
- Workers scale independently to process the backlog.
- Dead-Letter Queues (DLQs) capture poisoned or corrupted documents after 3 attempts without blocking the main queue."

---

### 21. How do you guarantee idempotency?
**Spoken Response:**
"In `src/workers/ingestion_worker.py` and our transactional endpoints:
1. Every incoming job payload includes an `idempotency_key` or cryptographic `content_hash`.
2. Before processing, the worker checks PostgreSQL using an atomic query. If a record with that hash is already marked `COMPLETED`, the job exits immediately with success.
3. For in-flight jobs, we acquire a distributed Redis lock with a lease timeout. If a duplicate message arrives from SQS while the first is processing, the second worker cannot acquire the lock and discards the duplicate."

---

### 22. How do you implement HITL?
**Spoken Response:**
"In LangGraph, we compile the state graph with `interrupt_before=['hitl_gate']`. 
1. When the Risk Assessor calculates a metric exceeding the tenant's risk policy (e.g., VaR > 5%), it transitions to `hitl_gate`.
2. LangGraph pauses execution, serializes the complete graph state to the checkpointer, and stores a `HITLTask` in PostgreSQL with status `PENDING`.
3. The API returns an HTTP 202 Accepted response with the `task_id`.
4. When a risk officer approves the task via `POST /api/v1/hitl/tasks/{id}/approve`, the service loads the checkpoint using the `thread_id`, updates state with the human's approval payload, and resumes execution seamlessly to generate the final report."

---

### 23. How do you perform disaster recovery?
**Spoken Response:**
"We maintain a Warm Standby Disaster Recovery posture with **RTO < 15 minutes** and **RPO < 1 minute**:
1. **Multi-AZ Foundation**: Primary services span 3 Availability Zones with automated sub-minute failovers for Aurora, Redis, and ALB.
2. **Continuous Database Replication**: Aurora PostgreSQL replicates automated snapshots to our secondary DR region (us-west-2).
3. **S3 Cross-Region Replication**: Document buckets automatically replicate filings to the DR region asynchronously.
4. **Infrastructure-as-Code**: 100% of our infrastructure is codified in Terraform modules. In a regional catastrophe, spinning up the secondary environment is achieved via `terraform apply -var-file=dr.tfvars`, provisioning identical networking, compute, and data tiers with zero manual steps."
