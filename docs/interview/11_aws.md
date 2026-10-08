# 11 — AWS Cloud Infrastructure, Terraform & Deployment Engineering

## 1. Component Analysis (9 Core Dimensions)

### 1. What Problem Does It Solve?
Manual infrastructure configuration in the AWS Management Console leads to configuration drift, security misconfigurations, non-repeatable deployments, and catastrophic downtime. Regulated financial systems require immutable Infrastructure-as-Code (IaC), multi-AZ redundancy, blue/green zero-downtime deployments, and least-privilege IAM policies.

### 2. Why Did We Choose Terraform and AWS?
- **Terraform 1.5+ Modules**: Declarative, repeatable infrastructure provisioning with complete environment separation across `dev`, `staging`, and `prod`.
- **AWS Bedrock Native Ecosystem**: Enterprise Anthropic Claude 3.5 and Titan models hosted within the AWS security perimeter under SOC2 and HIPAA compliance.
- **ECS Fargate Serverless Compute**: Eliminates EC2 operating system patching and cluster maintenance while integrating directly with AWS Application Load Balancers and CodeDeploy Blue/Green controllers.

### 3. What Alternatives Were Considered?
- **AWS CDK (Cloud Development Kit)**: Powerful, but Terraform was chosen for superior multi-cloud portability, declarative state inspection, and standard organizational approval workflows.
- **Kubernetes (EKS)**: Over-engineered for a focused microservice architecture. Running EKS would have added control plane costs, node group scaling management, and Kubernetes ingress controller overhead.

### 4. How Does It Work Internally?
```
terraform/
├── modules/
│   ├── networking/        ──► 3 AZs, Public Subnets, Private App Subnets, Private Data Subnets, NAT Gateways
│   ├── security/          ──► KMS Customer Managed Key, WAFv2, Secrets Manager, Bedrock Scoped IAM
│   ├── compute/           ──► ALB, Blue/Green Target Groups, ECS Fargate, 5-Policy Autoscaling
│   ├── database/          ──► Aurora Serverless v2 Multi-AZ, ElastiCache Redis 7.1
│   ├── storage_messaging/ ──► Versioned S3 with KMS & Lifecycle, SQS Primary & FIFO Queues + DLQs
│   ├── opensearch/        ──► OpenSearch 2.11 Multi-AZ, gp3 EBS, Dedicated Master Nodes
│   ├── dns_edge/          ──► Route53 DNS, CloudFront Global CDN, ACM TLS, HTTP API Gateway
│   └── monitoring/        ──► CloudWatch Metrics, Operations Dashboard, P1/P2 SNS Alarms
└── environments/
    ├── dev/               ──► Cost-optimized (1 NAT, single AZ DB/Redis, 1-4 tasks)
    ├── staging/           ──► Production parity (Dual NAT, Multi-AZ DB/Redis, 2-10 tasks)
    └── prod/              ──► High availability (3 NATs, 3 AZs, 4-50 tasks, Blue/Green CodeDeploy)
```

### 5. How Does It Scale?
- ECS Fargate autoscales tasks from 4 to 50 across 3 AZs based on ALB RequestCountPerTarget and latency step scaling.
- Aurora Serverless v2 scales from 2.0 to 32.0 ACUs in sub-second increments.
- SQS queues decouple bursty document ingestion from backend processing.

### 6. What Happens When It Fails?
- **Availability Zone Outage**: Infrastructure spans 3 AZs. If an entire AWS data center goes offline, traffic is seamlessly routed to the remaining two AZs by Route53, ALB, Aurora, and Redis.

### 7. How Is It Secured?
- **Zero Public Data Access**: Databases, Redis, OpenSearch, and ECS containers reside strictly in private subnets with no public IP addresses.
- **Least-Privilege IAM**: ECS task roles are strictly scoped to specific Bedrock model ARNs (`arn:aws:bedrock:*::foundation-model/anthropic.claude*`) and KMS keys.
- **WAF Protection**: ALB and CloudFront are shielded by WAF rules enforcing rate limiting, OWASP Top 10, and SQLi inspection.

### 8. How Is It Monitored?
- Comprehensive CloudWatch Dashboard (`copilot-operations-prod`) displaying ALB latency percentiles (p50/p95/p99), ECS CPU/Memory, SQS backlogs, and Aurora ACUs.

### 9. What Are the Trade-offs?
- **NAT Gateway Costs**: Running 3 dedicated NAT Gateways in production costs ~$100/month in idle AWS charges, but provides necessary fault-isolation across Availability Zones.

---

## 2. Spoken Interview Responses

### Interviewer: "How do you execute zero-downtime Blue/Green deployments in AWS ECS?"
**Spoken Response:**
"In institutional finance, taking the trading or research platform down for a maintenance window during trading hours is unacceptable. We implement **Automated Blue/Green Deployments using AWS CodeDeploy and Dual ALB Target Groups** in `terraform/modules/compute/main.tf`:

1. **Two Target Groups**: We define `target_group_blue` and `target_group_green`. In steady state, `blue` receives 100% of production traffic on ALB port 443.
2. **Deploying a New Version**: When a new container image is pushed to Amazon ECR, ECS triggers CodeDeploy. CodeDeploy spins up the new task revision and registers it with the idle `green` target group.
3. **Automated Health Checks**: CodeDeploy executes synthetic HTTP health checks (`/health/live` and `/health/ready`) against the test listener on port 8443 for 5 minutes.
4. **Traffic Shifting**: Once health checks pass, CodeDeploy begins traffic shifting (either canary `CodeDeployDefault.ECSCanary10Percent5Minutes` or linear `CodeDeployDefault.ECSLinear10PercentEvery1Minute`).
5. **Instant Rollback on Failure**: If any CloudWatch alarm fires during the shift—such as ALB 5xx errors > 1% or p95 latency > 1.0s—CodeDeploy immediately aborts the deployment and shifts 100% of traffic back to the healthy `blue` target group in seconds.
6. **Graceful Drain**: After a successful deployment, the old `blue` containers are kept running for a 5-minute termination grace period to allow in-flight financial calculations to complete before being decommissioned."

### Interviewer: "How do you perform Disaster Recovery (DR) and what are your RTO and RPO targets?"
**Spoken Response:**
"Our Disaster Recovery strategy is designed for a **Pilot Light / Warm Standby** model with explicit targets:
- **RTO (Recovery Time Objective)**: < 15 minutes.
- **RPO (Recovery Point Objective)**: < 1 minute.

Here is how we achieve this across all storage and compute tiers:
1. **Primary Multi-AZ Resiliency**: Within our primary region (us-east-1), every tier—ALB, ECS Fargate, Aurora Serverless, Redis, and OpenSearch—is distributed across 3 Availability Zones with automatic sub-minute failover.
2. **Database DR**: Aurora PostgreSQL maintains continuous automated snapshots to S3 with a 35-day retention window, encrypted under our Customer Managed KMS key. In addition, we configure cross-region automated snapshot replication to our DR region (us-west-2).
3. **Document Store DR**: S3 document buckets have cross-region replication (CRR) enabled with versioning. Every ingested 10-K and financial report is replicated asynchronously within seconds.
4. **Infrastructure Re-creation**: Because 100% of our infrastructure is codified in Terraform modules, spinning up the complete platform in a secondary region is executed via `terraform apply -var-file=dr.tfvars`, which provisions networking, compute, and data tiers deterministically without manual intervention."
