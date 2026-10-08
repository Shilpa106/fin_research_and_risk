# 03 — RAG Deep Dive & Information Retrieval Architecture

## 1. Component Analysis (9 Core Dimensions)

### 1. What Problem Does It Solve?
Standard vector retrieval fails on financial documents. SEC filings contain dense tabular disclosures, complex footnotes, cross-referenced credit covenants, and specialized vocabulary (e.g., "EBITDA adjustments under Section 4.02"). Standard chunking breaks financial tables, while pure cosine-similarity dense search misses exact ticker symbols, section headers, and numbers.

### 2. Why Did We Choose This Retrieval Architecture?
We engineered a **Three-Stage Hybrid RAG Pipeline**:
1. **Financial Document Parsing & Table-Aware Chunking**: Markdown preservation of HTML/XBRL tables with row/column context retention.
2. **Hybrid Retrieval (Dense + Sparse)**: Combines dense vector k-NN embeddings (Amazon Titan Text Embeddings v2, 1024-dim) with lexical BM25 token matching using **Reciprocal Rank Fusion (RRF)**.
3. **Cross-Encoder Reranking**: Re-scores top-50 candidate chunks using a cross-encoder model to produce the final top-5 most relevant chunks.

### 3. What Alternatives Were Considered?
- **Pure Vector Search (pgvector / Pinecone)**: Failed in testing on exact term matching. Searching for "Form 10-Q Item 1A" frequently returned Form 10-K Item 7 because semantic embeddings alone blurred section distinctions.
- **Naive Fixed-Size Chunking (500 tokens, 50 overlap)**: Cut balance sheets in half, separating line items from footnotes and producing hallucinated financial calculations.
- **Pure BM25 Search**: Failed on conceptual financial questions (e.g., "What are the company's interest rate sensitivity assumptions?" when the text says "rate vulnerability modeling").

### 4. How Does It Work Internally?
```
Raw Filing (10-K / 10-Q)
  │
  ▼
Table-Aware Chunking (Hierarchical Chunks + Table MD + Footnote References)
  │
  ├──► Dense Embeddings (Titan Text v2 1024d) ──┐
  │                                            ├──► OpenSearch Hybrid Index
  └──► Lexical BM25 Inverted Index ────────────┘
                                                     │
User Query ──────────────────────────────────────────┘
  │
  ▼
Query Processing (Financial Ticker Extraction + Synonyms)
  │
  ├──► OpenSearch k-NN Dense Search (Top 50)
  ├──► OpenSearch BM25 Sparse Search (Top 50)
  │
  ▼
Reciprocal Rank Fusion (RRF: Score = Σ 1 / (60 + rank))
  │
  ▼
Cross-Encoder Reranker (Rescore Top 50 -> Top 5 Chunks)
  │
  ▼
Cryptographic Verification & Grounding (SHA256 chunk hash check)
  │
  ▼
Prompt Injection to LLM with Strict Citation Constraints
```

### 5. How Does It Scale?
- OpenSearch 2.11 domain uses **gp3 storage** with 3,000 baseline IOPS and 125 MB/s throughput per node.
- Indexes are partitioned by tenant and quarter. Sharding allows parallel retrieval across multiple nodes.
- Cross-encoder reranking is executed on CPU-optimized worker threads with cached inference weights.

### 6. What Happens When It Fails?
- If OpenSearch is temporarily unreachable, the retrieval service catches the connection exception and falls back to **cached retrieval results in Redis**.
- If no cache is found, the agent returns an explicit system warning: *"Retrieval service degraded. Unable to verify real-time SEC filings. Proceeding with caution."* The agent will refuse to fabricate financial numbers.

### 7. How Is It Secured?
- **AST Tenant Boundary Enforcement**: The `TenantBoundaryEnforcer` injects a mandatory `{"term": {"tenant_id": current_tenant}}` filter directly into the OpenSearch boolean query before sending the HTTP request.
- **Document-Level Access Control (DAC)**: If a document has specific user role tags (e.g., `confidential_m_and_a`), the filter appends an authorization check matching the user's role list.

### 8. How Is It Monitored?
- Metrics: `rag.retrieval.latency_ms`, `rag.reranker.latency_ms`, `rag.cache_hit_ratio`, `rag.recall_at_k`.
- Tracing: OpenTelemetry spans record candidate chunk count, RRF scores, and cross-encoder scores for every search.

### 9. What Are the Trade-offs?
- **Hybrid Search Latency**: Combining dense vector search, BM25, and cross-encoder reranking takes ~150–250ms compared to ~40ms for pure BM25. In institutional finance, this latency trade-off is essential to eliminate bad investment recommendations.

---

## 2. Spoken Interview Responses

### Interviewer: "Why did you choose OpenSearch instead of just using PostgreSQL pgvector?"
**Spoken Response:**
"That's one of the most critical architectural decisions we made. Many teams default to `pgvector` because it keeps everything in PostgreSQL, but in a production enterprise financial application, `pgvector` falls short for three reasons:

1. **True Hybrid BM25 + Vector Search**: Financial queries demand both semantic vector similarity and exact lexical matching. If a user searches for *'Credit Agreement dated March 15, 2023, Section 8.01(b)'*, vector embeddings fail to isolate that exact clause. PostgreSQL's `tsvector` is basic full-text search; it does not provide true BM25 probabilistic relevance scoring, nor does it have built-in Reciprocal Rank Fusion (RRF) algorithms. OpenSearch has native, optimized RRF scoring combining BM25 and HNSW vector graphs in a single query.
2. **Resource Contention on the Primary Database**: Nearest-neighbor vector indexing (HNSW graphs) consumes massive amounts of RAM. If you run high-dimensional vector search on the same PostgreSQL instance handling user authentication, transactional audit logs, and HITL tasks, vector queries will evict database buffer pools, causing transactional slowdowns.
3. **Horizontal Sharding and Scale**: OpenSearch scales horizontally across dedicated data nodes and availability zones. As we ingest millions of pages of corporate filings, we scale search storage and compute independently of our relational database."

### Interviewer: "How does your system prevent hallucinated citations—so-called 'ghost citations'?"
**Spoken Response:**
"Ghost citations are when an LLM writes a convincing statement and appends `[Source: Apple 2023 10-K, Item 1A]` even though that statement never appeared in that filing. 

To prevent this, our pipeline enforces **Cryptographic Citation Grounding** in `src/security/sanitizer.py`:
1. Every chunk ingested into OpenSearch is tagged with an immutable metadata payload: `document_id`, `filing_type`, `page_number`, `line_start`, `line_end`, and a `sha256_hash` of the exact text chunk.
2. When chunks are provided to the agent, they are injected with strict markdown anchors: `<source id="chunk_abc123" doc="AAPL_10K_2023" page="45">`.
3. In the output guardrail, the synthesizer's response is parsed with regex. Every cited `source_id` is looked up against the exact list of chunks retrieved in that session's state. If the model cites a source ID that was not retrieved, or attributes facts to a non-existent document, the output sanitizer rejects the response, triggers a security audit event, and requests a regeneration with grounding enforcement."
