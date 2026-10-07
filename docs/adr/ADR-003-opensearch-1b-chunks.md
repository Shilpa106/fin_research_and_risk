# ADR-003: OpenSearch for Hybrid Retrieval at 1 Billion+ Chunks Scale

## Status
Accepted

## Context
The platform indexes over 100 million financial documents resulting in more than 1 billion searchable chunks (~12–24 TB of vectors and text). Retrieval must support both semantic vector similarity (e.g. concept-based risk factors) and lexical exact match (e.g. exact financial tickers like "BRK.A", specific accounting metrics like "ASC 842 lease liability", and CIK numbers).

## Decision
We select **OpenSearch 2.x (Amazon OpenSearch Service)** with k-NN HNSW vector search and BM25 inverted index hybrid retrieval, combined with Reciprocal Rank Fusion (RRF).

## Why This Technology Was Selected
1. **True Hybrid Retrieval in a Single Cluster**: OpenSearch natively unifies BM25 inverted index text search with k-NN vector search (utilizing FAISS and NMSLIB engines). Financial research fails on pure vector search when querying exact accounting line items or regulatory formulas. Hybrid search combines the precision of BM25 with the conceptual breadth of dense vectors.
2. **Proven 1B+ Vector Sharding & Clustering**: OpenSearch is built on Lucene's distributed architecture, capable of horizontally sharding across 24+ data nodes with replica durability, ILM (Index Lifecycle Management), and warm/cold ultra-warm storage tiering.
3. **Multi-Tenant Shard Routing**: Supports routing keys (`routing=tenant_{tenant_id}`), allowing queries to target the specific physical shards containing a tenant's documents, avoiding expensive cluster-wide scatter-gather queries.

## Alternatives Considered
- **Pinecone / Weaviate / Qdrant**: Excellent pure vector databases, but poor or second-class inverted index / BM25 lexical support for exact financial disclosures, and significantly higher managed cost at 1B+ vectors with multi-tenancy.
- **pgvector (PostgreSQL)**: Unsuitable for 1B+ vectors; index build times on IVFFlat/HNSW at billion scale severely degrade Postgres I/O and exceed single-cluster memory limits.
