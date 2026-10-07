# Enterprise Financial Research & Risk Copilot — Security Architecture

## 1. Security Principles & Threat Model

The platform processes sensitive institutional financial data, proprietary trading strategies, material non-public information (MNPI), and client portfolio allocations. Security is designed following the **Zero Trust Architecture (NIST SP 800-207)** and Defense-in-Depth principles.

### Key Threats Addressed
1. **Tenant-Crossing Data Leakage**: Accidental or malicious retrieval of another financial institution's proprietary filings or portfolio holdings.
2. **Prompt Injection & Model Jailbreaking**: Adversarial inputs attempting to bypass financial advice disclaimers, extract underlying system prompts, or induce unauthorized tool execution.
3. **Data Exfiltration via Agent Tools**: Rogue or compromised agent tool calls attempting to transmit internal data to unauthorized external endpoints.
4. **Credential Theft & Session Hijacking**: Compromise of institutional API keys or analyst session tokens.
5. **Unauthorized Modification of Risk Reports**: Tampering with Value-at-Risk calculations or bypassing Human-in-the-Loop review gates.

---

## 2. Multi-Tenant Cryptographic & Logical Isolation

```
┌───────────────────────────────────────────────────────────────────────────┐
│                           TENANT ISOLATION MODEL                          │
└───────────────────────────────────────────────────────────────────────────┘
         Client Request (JWT Claim: tenant_id = 7f8a-4b2c)
                               │
                               ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ 1. API Gateway & Middleware Validation                                    │
│    - Verifies RS256 JWT signature against Tenant Identity Provider        │
│    - Injects tenant_id into contextvars (immutable per request)           │
└───────────────────────────────────────────────────────────────────────────┘
                               │
          ┌────────────────────┴────────────────────┐
          ▼                                         ▼
┌───────────────────────────────────┐     ┌───────────────────────────────────┐
│ 2. PostgreSQL Relational Store    │     │ 3. OpenSearch 1B+ Chunk Vector    │
│    SET LOCAL app.current_tenant_id│     │    routing = tenant_7f8a          │
│    Kernel Row-Level Security (RLS)│     │    filter: {"term": {"tenant_id": │
│    Enforced at Engine Level       │     │             "7f8a-4b2c"}}         │
└───────────────────────────────────┘     └───────────────────────────────────┘
          │                                         │
          ▼                                         ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ 4. Cryptographic Isolation (AWS KMS Envelope Encryption)                  │
│    - Customer Managed Key (CMK) per Tier-1 Institutional Tenant           │
│    - AES-256-GCM data key encryption for all stored files and chunks      │
└───────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Database Row-Level Security (RLS) Enforcement
Relational data isolation does not rely on application `WHERE` clauses. Instead, PostgreSQL kernel Row-Level Security is strictly enforced:

```sql
-- Enforce RLS on all sensitive tables
ALTER TABLE financial_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE hitl_review_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE hitl_audit_logs ENABLE ROW LEVEL SECURITY;

-- Strict tenant matching policy
CREATE POLICY tenant_isolation_documents ON financial_documents
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
```
When acquiring a connection from the pool, FastAPI middleware executes:
`SET LOCAL app.current_tenant_id = '<tenant_id>';` inside the active transaction block. Any query attempting to access another tenant's rows returns zero rows, even under application software defects.

### 2.2 OpenSearch Shard Routing & Compulsory Filters
To prevent tenant-crossing vector retrieval across 1B+ chunks:
1. Every chunk is indexed with a physical routing key: `routing=tenant_{tenant_id}`.
2. The Retrieval Service query builder injects a mandatory non-overridable filter clause:
   ```json
   {
     "filter": [
       {"term": {"tenant_id": "{authenticated_tenant_id}"}}
     ]
   }
   ```
3. Queries without an authenticated tenant context are rejected by the Retrieval Service before reaching the OpenSearch cluster.

---

## 3. Authentication, Authorization & RBAC

### 3.1 Authentication
- **Enterprise Federation**: SAML 2.0 and OIDC integration with institutional Identity Providers (Okta, Microsoft Entra ID / Azure AD, Ping Identity).
- **Session Tokens**: Asymmetric signed JSON Web Tokens (RS256 / ES256) with short 15-minute TTL.
- **Refresh Token Rotation**: Opaque cryptographically random refresh tokens stored in Redis with one-time-use invalidation and family revocation upon reuse detection.
- **M2M API Keys**: 256-bit entropy keys hashed using SHA-256 before database storage. Raw keys are never stored or logged.

### 3.2 Role-Based Access Control (RBAC) Matrix

| Business Capability | Viewer | Research Analyst | Risk Manager | Compliance Officer | Tenant Admin |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Search Public SEC Filings | ✅ | ✅ | ✅ | ✅ | ✅ |
| Query Research Copilot | ✅ (Read) | ✅ | ✅ | ✅ | ❌ |
| Upload Institutional Documents | ❌ | ✅ | ✅ | ❌ | ❌ |
| Run Portfolio VaR Simulations | ❌ | ❌ | ✅ | ❌ | ❌ |
| Trigger Stress Tests | ❌ | ❌ | ✅ | ❌ | ❌ |
| Review / Approve HITL Tasks | ❌ | ❌ | ✅ | ✅ | ❌ |
| Modify AI Guardrail Rules | ❌ | ❌ | ❌ | ✅ | ❌ |
| View Regulatory Audit Logs | ❌ | ❌ | ❌ | ✅ | ✅ |
| Manage Users & API Keys | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## 4. AI Guardrails & Prompt Injection Defense

The platform enforces a layered guardrail pipeline on every AI interaction:

```
User Query ──► [Input Sanitization] ──► [Bedrock Guardrails] ──► [LLM Gateway]
                                                                        │
Final Memo ◄── [Audit Logging]     ◄── [Output Guardrails]  ◄───────────┘
```

1. **Input Layer (Pre-Inference)**:
   - Regex and semantic classifier scanning for prompt injection patterns ("ignore previous instructions", "system override", "jailbreak").
   - PII and MNPI scrubbing: Tax IDs, credit card numbers, executive personal phone numbers, and restricted insider trading lists.
2. **Foundation Model Layer**:
   - System prompts enforced via immutable Bedrock system instruction parameters.
   - Claude 3.5 Sonnet temperature constrained to $\le 0.2$ to minimize hallucination variance.
3. **Output Layer (Post-Inference)**:
   - **AWS Bedrock Guardrails**: Automated topic policy evaluation blocking prohibited financial claims ("guaranteed profit", "risk-free yield").
   - **Groundedness Verification**: Verifies that every factual financial metric corresponds to an extracted chunk citation. If groundedness score $< 0.85$, the response is blocked from publication.

---

## 5. Model Context Protocol (MCP) Tool Sandboxing

Agent tools interact exclusively via the Model Context Protocol (MCP):
- **Least Privilege Tool Scopes**: MCP servers run in network-isolated containers within private subnets.
- **Input Validation**: Tool parameters (e.g. ticker symbols, CIK codes, fiscal years) are strictly validated against Pydantic schemas before invocation.
- **Read-Only Enactment**: SEC EDGAR and Market Data MCP tools operate strictly in read-only mode, preventing unauthorized mutation of external resources.
- **Egress Restrictions**: MCP containers have zero internet gateway access except to explicit financial upstream APIs configured via AWS Security Groups and egress proxies.

---

## 6. Regulatory Compliance & Audit Immutability

- **SEC Rule 17a-4 & FINRA Rule 4511**: Mandates retention of financial communications and research records in Write-Once-Read-Many (WORM) format for 3 to 6 years.
- **S3 Object Lock (Compliance Mode)**: Audit logs and generated research memos are replicated to an AWS S3 bucket configured with **S3 Object Lock in Compliance Mode**, preventing deletion or overwriting even by the AWS root account.
- **Traceability**: Every record contains the W3C TraceContext `trace_id`, user identity, authenticated tenant UUID, retrieved chunk hashes, and exact model parameters used during synthesis.
