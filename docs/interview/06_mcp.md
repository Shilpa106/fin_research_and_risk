# 06 — Model Context Protocol (MCP) & Tool Gateway

## 1. Component Analysis (9 Core Dimensions)

### 1. What Problem Does It Solve?
Connecting LLMs directly to arbitrary Python functions or external APIs creates severe security, maintainability, and operational hazards. Without a standardized protocol, every tool requires custom parameter parsing, lacks centralized RBAC access control, allows prompt-injected tool invocations, and risks leaking credentials or executing arbitrary code.

### 2. Why Did We Choose the Model Context Protocol (MCP)?
We adopted Anthropic's **Model Context Protocol (MCP)** specification to establish an enterprise-grade, standardized boundary between agents and backend systems:
- **Standardized Tool Discovery & Contract**: Tools expose strongly-typed JSON-RPC interfaces and schemas regardless of implementation language.
- **Unified Security Boundary**: Every tool execution passes through an explicit gateway interceptor that enforces RBAC, rate limits, and parameter validation.
- **Decoupled Architecture**: Financial calculation engines, SEC EDGAR integrations, and market data feeds can run as isolated microservices or internal processes without modifying agent code.

### 3. What Alternatives Were Considered?
- **Ad-Hoc LangChain Tools (`@tool` decorator)**: Tightly coupled to the Python runtime; difficult to enforce centralized cross-tenant authorization or export across disparate microservices.
- **OpenAPI / Swagger Tool Auto-Generation**: Resulted in overly complex, bloated schemas that degraded model tool-calling accuracy.
- **Direct Database Execution (e.g. Text-to-SQL)**: Strictly rejected in institutional finance due to the unacceptable risk of unintended updates, deletions, or data extraction across tenant boundaries.

### 4. How Does It Work Internally?
```
Agent Tool Use Request {"name": "calculate_portfolio_risk", "arguments": {...}}
     │
     ▼
[MCP Gateway Interceptor]
     │
     ├── 1. Tool Allowlist Check (Is tool registered?)
     ├── 2. Tenant RBAC Guard (Does user have `tools:execute:risk` permission?)
     ├── 3. Argument Sanitizer (Check for SQLi, Path Traversal, Shell Injections)
     ├── 4. Pydantic Schema Validation (Validate ranges, types, non-nulls)
     ├── 5. Tenant Scope Injection (Inject caller's tenant_id)
     │
     ▼
[MCP Execution Handler] ──► Deterministic Math / SEC EDGAR API
     │
     ▼
Structured Output Sanitization ──► Return to Agent Context
```
Implemented Tools in `src/mcp/`:
1. `sec_edgar_lookup`: Queries SEC EDGAR API for CIKs, filings, and 10-K/10-Q accession numbers.
2. `portfolio_risk_calculator`: Deterministic Monte Carlo simulation computing 95% and 99% Value-at-Risk (VaR) and Expected Shortfall.
3. `dcf_valuation_engine`: Multi-period Discounted Cash Flow valuation with weighted average cost of capital (WACC) sensitivity analysis.
4. `market_data_feed`: Retrieval of real-time prices, historical volatility, and beta metrics.

### 5. How Does It Scale?
- Tool execution is asynchronous and non-blocking.
- Heavy numerical algorithms (e.g., 10,000-run Monte Carlo simulations) run in process pools or dedicated worker queues to keep the FastAPI asyncio loop responsive.

### 6. What Happens When It Fails?
- If an external tool times out (default 5.0s timeout) or returns an error:
  1. The MCP Gateway catches the exception.
  2. It formats a structured error message: `{"status": "error", "message": "Market data provider timed out after 5.0s. Use cached close prices."}`.
  3. The error is returned to the model as a tool result, allowing the model to adapt and proceed with available data rather than crashing.

### 7. How Is It Secured?
- **Injection Sanitization**: Arguments are scanned for command injection (`rm -rf`, `|`, `;`), path traversal (`../..`), and SQL injection attempts.
- **Tenant Isolation**: Tools that query tenant records enforce strict tenant ownership checks. A user from Tenant A cannot pass a `portfolio_id` belonging to Tenant B.

### 8. How Is It Monitored?
- Metrics: `mcp.tool_invocation.count`, `mcp.tool_invocation.latency_ms`, `mcp.tool_invocation.errors`, `mcp.unauthorized_invocations`.
- Structured audit logs capture `tool_name`, `user_id`, `tenant_id`, and execution duration.

### 9. What Are the Trade-offs?
- **Serialization Overhead**: JSON-RPC serialization between the agent and tools adds a few milliseconds of latency compared to direct in-memory function calls, but the security and decoupled isolation benefits are non-negotiable.

---

## 2. Spoken Interview Responses

### Interviewer: "How do you secure your MCP tools against malicious prompt injections?"
**Spoken Response:**
"When an agent calls an MCP tool, the input parameters originate from an LLM that might have been manipulated by an indirect prompt injection contained within an untrusted 10-K filing.

We protect our MCP gateway using a **Four-Stage Defense-in-Depth Pipeline** in `src/mcp/gateway.py`:
1. **RBAC Authorization**: We verify that the caller's JWT token has explicit permission to execute the requested tool. For instance, a junior analyst role cannot call portfolio rebalancing or trade tools.
2. **Schema & Strict Type Enforcement**: All arguments are validated against strict Pydantic schemas. If a field expects a float between 0.0 and 1.0, any string attempt or out-of-bound injection is rejected before execution.
3. **Malicious Input Sanitization**: Parameters are scrubbed through our security guards (`src/security/sanitizer.py`) for classic injection vectors—SQL injection keywords, shell metacharacters (`;&|`), directory traversal strings (`../`), and script tags.
4. **Mandatory Tenant Context Injection**: The agent cannot supply or override the `tenant_id` parameter. The MCP gateway strips any tenant argument from the model and injects the cryptographically validated `tenant_id` from the request context. This makes cross-tenant data access through tool arguments impossible."

### Interviewer: "What happens if an external tool like SEC EDGAR or market data hangs?"
**Spoken Response:**
"In an agent loop, a hanging tool call will freeze the entire execution graph and cause user-facing timeouts. 

In our MCP Client implementation:
- Every tool invocation is wrapped in an explicit `asyncio.wait_for(..., timeout=5.0)` boundary.
- If the EDGAR service fails to respond within 5 seconds, the task is cancelled, and our gateway catches the `asyncio.TimeoutError`.
- Instead of throwing a 500 error back to the user, the gateway constructs a clean JSON diagnostic payload: `{'tool': 'sec_edgar_lookup', 'status': 'timeout', 'retryable': true, 'error': 'Upstream SEC EDGAR API latency exceeded SLA'}`.
- This payload is injected into the LangGraph state as the tool's result. Claude 3.5 Sonnet parses the error, notes in its reasoning that real-time filing data is temporarily unavailable, falls back to previously indexed filings in our OpenSearch store, and informs the user transparently."
