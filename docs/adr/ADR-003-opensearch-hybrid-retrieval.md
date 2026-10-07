# ADR-003: OpenSearch for Hybrid Retrieval at 1 Billion+ Chunks Scale

## Status
Accepted

## Context
The platform indexes over 100 million financial documents resulting in more than 1 billion searchable chunks (~32 TB of vectors, text, and metadata). Retrieval must combine semantic conceptual matching (e.g., "supply chain disruption risk") with exact lexical matching (e.g., "ASC 842 lease liability", "Item 1A", "BRK.A", CIK numbers) at sub-50ms query latency under 10,000 API RPS.

---

## Technical Evaluation (The 9 Architectural Dimensions)

### 1. Why this technology?
OpenSearch 2.x natively unifies Lucene's industry-leading BM25 inverted index text search with k-NN dense vector search (utilizing FAISS and NMSLIB HNSW engines) inside a single distributed cluster. It supports Reciprocal Rank Fusion (RRF) for true hybrid scoring, physical shard routing (`routing=tenant_{tenant_id}`) for tenant isolation, and horizontal sharding across 24+ nodes.

### 2. What alternatives were considered?
- **Pinecone (Managed Vector Database)**
- **Milvus / Qdrant**
- **pgvector (PostgreSQL extension)**
- **Elasticsearch (Elastic NV)**

### 3. Why were they rejected?
- **Pinecone / Milvus / Qdrant**: Excellent pure vector databases, but poor or second-class inverted index lexical BM25 support. Pure vector search fails miserably on exact financial regulatory terms, accounting line items, and specific numbers. Implementing separate vector (Pinecone) + lexical (Elastic) stores requires two-phase distributed joins and dual maintenance costs.
- **pgvector**: Unviable at 1B+ vectors. Re-indexing 1B vectors in PostgreSQL exhausts RAM and degrades write performance.
- **Elasticsearch**: Licensing is proprietary/SSPL; Amazon OpenSearch Service is 100% open-source Apache 2.0 with native AWS VPC, IAM, and KMS integration.

### 4. What happens at 10M users?
User queries hit the cluster concurrently. OpenSearch's distributed architecture with 200 primary shards + 200 replica shards across 24 data nodes ensures that queries are parallelized across hundreds of CPU cores, maintaining P95 search latency $< 50\text{ ms}$.

### 5. What happens if the component fails?
- Every primary shard has an active replica shard on a different node in a separate Availability Zone.
- If a data node terminates, the dedicated cluster managers promote replica shards to primary within 5 seconds with zero search downtime.
- AWS Auto Scaling launches replacement nodes, and peer shard recovery restores replica balance in the background.

### 6. How does it scale?
- **Horizontal Sharding**: Additional data nodes (`r6g.4xlarge.search`) can be added to the cluster with zero downtime.
- **UltraWarm / Cold Tiering**: Historical filings ($> 3$ years old) migrate to S3-backed UltraWarm storage, reducing cluster compute requirements by 65%.

### 7. What is the operational cost?
24 Data Nodes (`r6g.4xlarge.search`) + 3 Dedicated Managers + 36 TB gp3 EBS costs ~$18,900/month under 3-Year Reserved Instances.

### 8. What is the AWS production equivalent?
**Amazon OpenSearch Service 2.x** with Dedicated Cluster Managers and Multi-AZ with Standby.

### 9. What is the local-development equivalent?
Single-node OpenSearch 2.x container via Docker Compose (`opensearchproject/opensearch:2.15.0`) or local in-memory NumPy cosine similarity fallback for unit testing.
