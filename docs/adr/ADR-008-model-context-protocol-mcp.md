# ADR-008: Model Context Protocol (MCP) for Enterprise Financial Tool Integration

## Status
Accepted

## Context
The financial copilot must integrate with external and internal systems: SEC EDGAR filing endpoints, real-time equity market data, treasury yield curves, and proprietary portfolio risk engines. Allowing LLMs to invoke arbitrary system code or directly embedding external proprietary APIs into prompts creates tight vendor coupling and severe security vulnerabilities.

---

## Technical Evaluation (The 9 Architectural Dimensions)

### 1. Why this technology?
The **Model Context Protocol (MCP)** is an open, standardized protocol created to connect AI applications to external data sources and tools via JSON-RPC 2.0. It provides standardized schema negotiation, tool discovery, structured parameter validation, and process isolation.

### 2. What alternatives were considered?
- **Direct Python Function Calling in Application Code**
- **Custom REST API Microservices for Tools**
- **GraphQL Tool Gateways**
- **OpenAI Assistants API Tool Bindings**

### 3. Why were they rejected?
- **Direct Python Function Calling**: Tightly couples tool implementations to the agent codebase. If an SEC filing scraper crashes or memory-leaks, it brings down the main application worker. Prevents running tools in isolated security boundaries.
- **Custom REST API Microservices**: Lacks standardized tool definition schemas; requires writing custom adapter code for every agent framework and LLM provider.
- **GraphQL**: Overly complex query parsing overhead for simple tool invocations and lacks native agentic tool discovery conventions.
- **OpenAI Assistants Bindings**: Proprietary lock-in to OpenAI cloud infrastructure.

### 4. What happens at 10M users?
MCP tool servers run in independent autoscaling container fleets behind internal load balancers. High-frequency queries (e.g., live stock quotes) are cached at the MCP Gateway layer via Redis, preventing downstream rate-limiting from external market providers.

### 5. What happens if the component fails?
- If an MCP tool server (e.g. SEC EDGAR) fails or times out, the MCP client raises a typed tool exception.
- The LangGraph agent runtime captures the error, appends it to `tool_outputs`, and gracefully informs the analyst or switches to a fallback secondary data provider.

### 6. How does it scale?
Horizontally. Each MCP server (SEC Edgar MCP, Market Data MCP, Risk MCP) is a lightweight stateless micro-container scaling independently on AWS ECS based on CPU and request queue depth.

### 7. What is the operational cost?
Minimal compute footprint: 2–4 small ECS tasks per tool server costs ~$250/month in aggregate.

### 8. What is the AWS production equivalent?
**MCP Tool Servers on AWS ECS / AWS Lambda** running in private VPC subnets with strictly scoped egress security groups.

### 9. What is the local-development equivalent?
Local Python FastMCP servers running on `localhost:8001` and `localhost:8002` or mock in-process tool handlers.
