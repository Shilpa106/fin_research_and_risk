# ADR-005: Apache Kafka (Amazon MSK) for Event Streaming and Document Ingestion

## Status
Accepted

## Context
Ingesting 100M+ financial documents, processing complex SEC tables, and generating 1B+ vector embeddings involves massive asynchronous, I/O-intensive workloads. During market open and quarterly earnings seasons, ingestion spikes to 50 documents/second (500 chunks/second). The ingestion pipeline must be decoupled from client-facing API response paths.

---

## Technical Evaluation (The 9 Architectural Dimensions)

### 1. Why this technology?
Apache Kafka is the industry-standard distributed event streaming platform. It offers high write throughput (hundreds of thousands of messages/second), durable partition log retention, consumer group autoscaling, message ordering per key (`tenant_id:ticker`), and independent replayability if downstream ingestion workers or vector embedders encounter transient failures.

### 2. What alternatives were considered?
- **AWS SQS / SNS**
- **RabbitMQ**
- **Redis Streams**
- **AWS Kinesis Data Streams**

### 3. Why were they rejected?
- **AWS SQS**: Good for basic task queues, but lacks partition key ordering guarantees at high throughput, does not support multiple independent consumer group fan-outs without SNS fan-out architectures, and has higher operational cost at billions of messages.
- **RabbitMQ**: Traditional AMQP message broker where messages are deleted upon acknowledgment. Cannot replay historical event streams if a bug is discovered in document chunking or embedding models.
- **Redis Streams**: Good for lightweight streaming, but lacks durable multi-terabyte disk persistence, distributed partitioning across nodes, and enterprise replication.
- **AWS Kinesis**: More expensive at high shard counts and has rigid 2 MB/sec per-shard egress limits.

### 4. What happens at 10M users?
User activities (uploads, filing ingestions) publish lightweight event envelopes to Kafka. Kafka decouples user traffic from ingestion workers, ensuring that even if 100,000 users upload documents simultaneously, API response times remain $< 20\text{ ms}$ while Kafka buffers the workload safely on disk.

### 5. What happens if the component fails?
- Amazon MSK runs 3 brokers across 3 Availability Zones with a replication factor of 3 and `min.insync.replicas = 2`.
- If an individual broker fails, client producers and consumers automatically connect to remaining in-sync replicas without message loss.

### 6. How does it scale?
Horizontally by increasing partition counts (e.g. from 32 to 64 partitions) and adding MSK broker instances (`kafka.m5.2xlarge`). Consumer worker fleets scale out dynamically using Kubernetes/ECS KEDA autoscalers monitoring Kafka consumer group lag.

### 7. What is the operational cost?
3 Brokers (`kafka.m5.2xlarge`, 6 TB storage across 3 AZs) costs ~$1,400/month under 3-Year Commitments.

### 8. What is the AWS production equivalent?
**Amazon Managed Streaming for Apache Kafka (Amazon MSK)**.

### 9. What is the local-development equivalent?
Local Apache Kafka + Zookeeper / KRaft container via Docker Compose (`confluentinc/cp-kafka:7.6.0`) on `localhost:9092`.
