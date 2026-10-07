# ADR-009: Amazon S3 with Object Lock for Document Storage and Regulatory WORM Compliance

## Status
Accepted

## Context
The platform stores over 100 million raw financial documents (SEC 10-K, 10-Q, 8-K HTML/PDFs, earnings audio transcripts, proprietary research notes) totaling 25+ TB, plus an immutable regulatory audit trail for compliance with SEC Rule 17a-4 and FINRA Rule 4511.

---

## Technical Evaluation (The 9 Architectural Dimensions)

### 1. Why this technology?
Amazon S3 provides 99.999999999% (11 9's) data durability, virtually infinite horizontal scalability, S3 Intelligent-Tiering and Glacier archival, native Server-Side Encryption with Customer Managed Keys (SSE-KMS), and **S3 Object Lock in Compliance Mode** (which mathematically guarantees Write-Once-Read-Many WORM compliance).

### 2. What alternatives were considered?
- **AWS Elastic File System (EFS)**
- **Amazon EBS Volumes**
- **Relational BLOB Storage in PostgreSQL**
- **Self-Hosted MinIO on EC2 / Ceph Storage**

### 3. Why were they rejected?
- **EFS / EBS**: Prohibitively expensive for 25+ TB of cold/warm document storage ($0.30/GB-month for EFS vs $0.023/GB-month for S3). EBS lacks multi-region replication and serverless HTTP access.
- **Relational BLOB in PostgreSQL**: Storing 25 TB of raw PDF files inside PostgreSQL causes severe WAL log bloat, inflates backup/restore times from minutes to days, and exhausts RDS disk bandwidth.
- **Self-Hosted MinIO / Ceph**: Incurs massive operational burden to maintain 11 9's durability, requires disk replacement and hardware operations, and does not provide certified SEC Rule 17a-4 WORM compliance out of the box.

### 4. What happens at 10M users?
S3 automatically scales to support millions of concurrent read requests. Document URLs are signed using pre-signed S3 URLs or fronted by Amazon CloudFront edge caching, offloading all document retrieval bandwidth from application servers.

### 5. What happens if the component fails?
- S3 automatically replicates objects across a minimum of 3 Availability Zones.
- S3 Cross-Region Replication (CRR) replicates all documents and audit records to a secondary AWS region (`us-west-2`), achieving RPO = 0 even in a regional disaster.

### 6. How does it scale?
Scales automatically with zero capacity provisioning. Supports up to 3,500 PUT/POST/DELETE requests/second and 5,500 GET/HEAD requests/second per prefix. By partitioning S3 prefixes by `tenant_id/ticker/year`, S3 throughput is effectively unlimited.

### 7. What is the operational cost?
25 TB S3 Standard + 50 TB Glacier Flexible Archive + S3 Object Lock costs ~$650–$850/month under Intelligent-Tiering.

### 8. What is the AWS production equivalent?
**Amazon Simple Storage Service (Amazon S3)** with S3 Intelligent-Tiering, SSE-KMS, and S3 Object Lock Compliance Mode.

### 9. What is the local-development equivalent?
Local S3-compatible **MinIO container** via Docker Compose (`minio/minio`) or local filesystem mock storage directory.
