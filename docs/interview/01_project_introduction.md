# 01 — Project Introduction & Executive Pitch

## 1. The High-Impact Executive Pitch (Spoken Response)

> *"If an interviewer asks: 'Can you give me an overview of the Enterprise Financial Research & Risk Copilot, what it does, and why it was built?'"*

**Spoken Response:**
"At a high level, the Enterprise Financial Research & Risk Copilot is a production-grade, multi-tenant GenAI platform purpose-built for institutional asset management, private equity, and corporate risk underwriting. 

In institutional finance, portfolio managers and quantitative risk analysts spend hundreds of hours manually combing through thousands of pages of SEC filings—10-Ks, 10-Qs, 8-Ks—earnings call transcripts, and real-time market data to assess creditworthiness, compute Value-at-Risk (VaR), and stress-test portfolios under macroeconomic shock scenarios like interest rate spikes or liquidity freezes. 

The core challenge isn't just generating text; it's that hallucinations, data leakage across institutional tenants, ungrounded financial calculations, or unvetted autonomous actions are completely unacceptable under SEC, FINRA, and SOC2 regulations.

To solve this, we engineered an end-to-end platform featuring:
1. A **Deterministic Multi-Agent Orchestration Layer** powered by LangGraph, decomposing complex research and risk workflows into specialized research, risk assessment, and synthesis agents with a state machine rather than an uncontrolled single-prompt agent.
2. A **Strictly Isolated Hybrid RAG Engine** in OpenSearch that pairs dense vector embeddings with sparse BM25 lexical search and cross-encoder reranking, cryptographically enforcing tenant boundaries at the query AST level to prevent cross-tenant data leakage.
3. An enterprise **Model Context Protocol (MCP) Tool Gateway** enabling agents to execute deterministic financial tools—such as Monte Carlo simulations, discounted cash flow (DCF) modeling, and EDGAR filings lookups—under strict RBAC and schema validations.
4. An **AI Gateway** providing multi-provider routing (AWS Bedrock Claude 3.5 Sonnet and Haiku, with fallback circuit breakers), semantic caching in Redis, and token/cost budgets.
5. A **Human-in-the-Loop (HITL) Governance Gate** that intercepts high-impact operations—like portfolio rebalancing or significant VaR anomaly alerts—requiring cryptographically signed two-man approvals before any action executes.
6. A **Production AWS Infrastructure** defined in Terraform with multi-AZ Aurora PostgreSQL Serverless v2, ElastiCache Redis, ECS Fargate blue/green deployments, WAF, KMS encryption, and distributed OpenTelemetry observability.

Everything in this platform is built around empirical correctness, zero ungrounded financial claims, and strict institutional isolation."

---

## 2. Core Architectural Pillars

| Component | Technical Role in Platform | Codebase Location |
|---|---|---|
| **Multi-Agent Runtime** | State-machine driven analyst & risk assessor graph with cycle limits | `src/agents/` |
| **Hybrid Retrieval (RAG)** | Dense + BM25 Reciprocal Rank Fusion with tenant boundary filter | `src/rag/` |
| **MCP Tool Gateway** | Standardized tool discovery, RBAC validation, and argument guardrails | `src/mcp/` |
| **AI Gateway** | Multi-model routing (Bedrock Claude/Titan), fallback circuit breaker, cost tracking | `src/ai_gateway/` |
| **Security & Guardrails** | Multi-layer input/output sanitization, PII masking, ghost citation check | `src/security/` |
| **HITL Engine** | Interception of high-risk workflows, state persistence, approval lifecycle | `src/application/services/hitl_service.py` |
| **Observability** | OpenTelemetry metrics, traces, structured JSON logging with Correlation IDs | `src/observability/` |
| **Evaluation Platform** | Automated CI regression gate for Context Recall, Faithfulness, and Tool Accuracy | `src/evaluation/` |
| **Cloud Infrastructure** | Multi-AZ Terraform modules across `dev`, `staging`, and `prod` | `terraform/` |

---

## 3. High-Value Interview Q&A Walkthrough

### Q1: "What problem does this platform solve that an enterprise couldn't solve with standard ChatGPT Enterprise or Microsoft Copilot?"
**Spoken Response:**
"Off-the-shelf enterprise chatbots fail in institutional finance for three primary reasons:
1. **Lack of Deterministic Financial Reasoning**: LLMs cannot perform reliable multi-period discounted cash flow calculations or Monte Carlo portfolio variance simulations; they hallucinate math. We decouple retrieval from calculation by routing mathematical operations through audited, deterministic MCP tools.
2. **Multi-Tenant Boundary Security**: Standard enterprise search lacks fine-grained document and tenant-level access control. In our platform, every retrieval vector query automatically injects tenant and permission filter clauses directly into the OpenSearch DSL before execution. A hedge fund cannot retrieve data belonging to another firm, even if their query strings are identical.
3. **Auditability and Autonomous Agency Risk**: Regulatory compliance demands strict traceability. Every claim must cite verified source chunks with exact line offsets (preventing ghost citations), and every high-consequence recommendation must pass an immutable Human-in-the-Loop approval gate with signed audit trails stored in PostgreSQL and SQS FIFO queues."

### Q2: "Can you walk me through the end-to-end request lifecycle when a user submits a complex portfolio stress-test query?"
**Spoken Response:**
"Sure. Let's trace a user query like *'Stress-test Portfolio A against a 150bps interest rate shock using our Q2 credit agreements'*:

1. **Edge & Ingress**: The HTTPS request enters AWS CloudFront CDN, passes AWS WAF inspection (rate limiting, SQLi, and prompt injection filters), and hits our Application Load Balancer.
2. **API Middleware Stack**: FastAPI receives the request. The `CorrelationIdMiddleware` extracts or generates a UUID `request_id` and OpenTelemetry `trace_id`. The auth guard verifies the JWT Bearer token, decodes tenant claims, and enforces RBAC permissions.
3. **Orchestrator Agent**: The request enters the LangGraph workflow. The Orchestrator analyzes the intent and initializes a typed state containing tenant context, conversation history, and tool invocation budgets.
4. **Research Sub-Agent**: The Research Agent queries the RAG service. The query processor extracts entities and executes a hybrid search against OpenSearch—combining Bedrock Titan dense embeddings with BM25 keyword matching, filtered strictly by `tenant_id`. Chunks are reranked via a cross-encoder model, and top chunks are returned with cryptographic hashes.
5. **Risk Assessor Sub-Agent**: The Risk Agent recognizes a mathematical stress-test requirement and invokes an MCP tool (`calculate_portfolio_risk`). The MCP gateway inspects the tool call, verifies tenant authorization, sanitizes parameters, executes the calculation engine, and returns deterministic VaR metrics.
6. **HITL Interception**: Because the calculated portfolio VaR exceeds the tenant's configured threshold (e.g., VaR > 5%), the state machine halts execution. It transitions the state to `PAUSED_FOR_HUMAN`, creates an immutable `HITLTask` in PostgreSQL, and alerts risk officers.
7. **Synthesis & Output Guardrails**: Once approved, the Synthesizer compiles the final analysis. Before returning to the client, the Output Security Guardrail validates that citations correspond to real retrieved chunks, verifies that no PII or sensitive keys leaked, appends the mandatory SEC regulatory disclaimer, and streams the response to the user."

---

## 4. Difficult Interviewer Follow-Ups

### Follow-Up: "Why not just build a single mega-prompt with all tools attached instead of a multi-agent system?"
**Spoken Response:**
"We actually evaluated a single-agent mega-prompt early on, and it broke down immediately. When you feed an LLM twenty tools and a 50-page credit agreement prompt, you face three critical failure modes:
1. **Tool Distraction & Hallucination**: Model tool selection accuracy drops significantly when the tool namespace is overcrowded. Claude or GPT will select the wrong tool or fabricate parameters.
2. **Context Window Contamination**: Financial 10-K analysis requires dense retrieval context. Mixing financial statement extraction with Monte Carlo risk formulas bloats the prompt, diluting attention and increasing prompt token costs by over 400%.
3. **Lack of Governance Boundaries**: A single agent cannot enforce separation of duties. By isolating the Research Analyst (read-only document retrieval) from the Risk Assessor (deterministic calculations) and Orchestrator (workflow routing), each agent operates with a focused prompt, specialized tools, and isolated failure domains."
