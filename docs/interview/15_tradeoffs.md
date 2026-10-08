# 15 — System Trade-Offs, Design Decisions & Engineering Pragmatism

## 1. Core Architectural Trade-Off Analysis

| Architectural Decision | Chosen Approach | Alternative Considered | Why We Made This Trade-Off | What We Gave Up (Cost / Complexity) |
|---|---|---|---|---|
| **1. Grounding vs. Latency** | Multi-Agent verification with hybrid retrieval & cross-encoder reranking | Single-prompt direct LLM streaming | Financial decisions require zero hallucinations; exact citations are legally mandatory under FINRA/SEC | Added ~800ms to 2.5s of latency compared to naive single-prompt streaming |
| **2. Search Engine Architecture** | Managed OpenSearch 2.11 cluster with native BM25 + k-NN RRF | PostgreSQL with `pgvector` extension | Financial filings require exact numerical, ticker, and covenant term matching that vector embeddings alone miss | Added operational overhead of managing OpenSearch cluster nodes, JVM, and index mappings |
| **3. Agent Architecture** | LangGraph explicit state-machine graph with typed state | Monolithic ReAct agent (e.g. LangChain AgentExecutor) | Prevents infinite loops; allows deterministic branching and durable checkpoints for human approvals | Required writing custom state schemas, conditional edge routers, and node handlers |
| **4. Tool Execution Boundary** | Model Context Protocol (MCP) with Pydantic schema validation | Unrestricted Python dynamic code execution (`exec` / code interpreter) | Financial calculations must be auditable and safe; dynamic code execution introduces arbitrary remote code execution risks | Cannot generate arbitrary on-the-fly Python scripts; all tools must be pre-registered and vetted |
| **5. Database Scaling** | Aurora PostgreSQL Serverless v2 + RDS Proxy | Statically provisioned RDS instance | Accommodates massive traffic spikes during earnings season while scaling down to 0.5–2 ACUs on weekends | ACU-hours carry a ~20% premium per GB compared to 3-year reserved static EC2/RDS instances |
| **6. Agency vs. Governance** | Mandatory Human-in-the-Loop (HITL) for high-impact actions | Fully autonomous trade execution / automated actions | Institutional compliance prohibits automated execution of high-VaR portfolio rebalancing without human sign-off | Workflows require external human intervention, introducing operational delays for pending tasks |

---

## 2. Spoken Interview Responses

### Interviewer: "What is the biggest architectural trade-off you made in this system, and would you change it?"
**Spoken Response:**
"The single biggest trade-off we made was **prioritizing deterministic factual grounding and verification over raw latency**.

In a consumer chatbot, users expect a response to start streaming in 400 milliseconds. But in our system:
1. We run hybrid retrieval in OpenSearch (dense embeddings + lexical BM25).
2. We run cross-encoder reranking over the top 50 chunks.
3. We decompose complex requests across specialized Research and Risk agents in LangGraph.
4. We verify citations against cryptographic SHA256 hashes of retrieved chunks in our output sanitizer.

This means an end-to-end multi-agent risk assessment takes between **2.5 to 6.0 seconds** to complete. 

If you ask me if I would change it—**absolutely not**. In institutional asset management, if an analyst receives an answer in 500 milliseconds that hallucinates an interest rate covenant or calculates an incorrect debt maturity date, the firm could execute a multi-million-dollar trade on bad data. Taking 4 seconds to guarantee that every single number is derived from verified SEC filings and audited calculation engines is the only acceptable engineering choice for enterprise finance."

### Interviewer: "Why did you accept the complexity of running OpenSearch alongside PostgreSQL instead of keeping a simple single-database architecture with pgvector?"
**Spoken Response:**
"Every engineer loves simplicity, and keeping everything in PostgreSQL with `pgvector` was our initial prototype. But as we tested realistic financial queries, `pgvector` created two critical bottlenecks that made it unviable for production:

1. **The Lexical Search Gap**: A portfolio manager frequently searches for exact clauses like *'Exhibit 10.1 Credit Agreement, Section 7.02 Negative Pledge'*. Vector embeddings encode semantic gist; they frequently map Section 7.02 to Section 7.03 because the surrounding legalese has an identical vector representation. PostgreSQL's built-in `tsvector` lacks modern BM25 scoring and native Reciprocal Rank Fusion. OpenSearch provides production-grade hybrid search out of the box.
2. **Buffer Pool Contention**: Running high-dimensional HNSW vector indexes requires massive RAM. In PostgreSQL, searching large vector indexes aggressively evicts standard relational data and B-tree indexes from the shared buffer pool. Under heavy concurrency, transactional queries on users and conversations slowed down by over 300%.

By separating transactional state into Aurora PostgreSQL and retrieval indexing into an OpenSearch cluster, we decoupled the failure domains and allowed each engine to be scaled independently according to its specific resource profile."
