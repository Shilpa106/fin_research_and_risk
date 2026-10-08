# 04 — Agentic AI & Autonomous Decision Systems

## 1. Component Analysis (9 Core Dimensions)

### 1. What Problem Does It Solve?
Complex financial research cannot be resolved with a single prompt. An institutional workflow like assessing the counterparty risk of a credit portfolio requires multiple sequential steps: discovering relevant credit agreements, extracting covenant terms, running Monte Carlo VaR models, calculating liquidity ratios, checking regulatory thresholds, and synthesizing the final recommendation. A monolithic LLM prompt either hallucinates intermediate calculations or loses track of multi-step dependencies.

### 2. Why Did We Choose a Multi-Agent Architecture?
We decomposed our workflow into specialized agents operating over a shared, immutable state:
- **Orchestrator Agent**: Analyzes intent, plans sub-tasks, and routes execution to specialists.
- **Financial Research Analyst Agent**: Specializes in document discovery, financial statement parsing, and RAG retrieval.
- **Quantitative Risk Assessor Agent**: Specializes in numerical calculations, stress-testing, and invoking deterministic MCP calculation tools.
- **Synthesis & Compliance Agent**: Reconciles findings, verifies citations, checks compliance constraints, and drafts the client report.

### 3. What Alternatives Were Considered?
- **ReAct (Reason + Act) Single-Loop Agent**: Prone to "agent drift", where the model wanders into unnecessary tool calls, burns hundreds of thousands of tokens, and exceeds latency SLAs.
- **Hard-Coded Sequential Python Pipeline**: Too rigid; unable to adapt dynamically when filings contain unexpected formats or require iterative query refinement.
- **Autonomous Multi-Agent Frameworks (AutoGen / CrewAI)**: Too conversational and nondeterministic for regulated banking environments. Models chat amongst themselves in loops with no mathematical guarantee of termination.

### 4. How Does It Work Internally?
```
User Request
     │
     ▼
[Orchestrator Node]
     │
     ├──► Route: Research Needed ──► [Research Analyst Node] ──► Query RAG
     │                                      │
     │                                 (Update State)
     │                                      ▼
     ├──► Route: Quantitative Risk ──► [Risk Assessor Node]  ──► Call MCP Tools
     │                                      │
     │                                 (Update State)
     │                                      ▼
     └──► Route: Synthesis Ready   ──► [Synthesizer Node]    ──► Verify Grounding
                                            │
                                            ▼
                                      Final Response
```
- **State Schema (`CopilotState`)**: A typed Pydantic/TypedDict model storing `messages`, `tenant_id`, `current_plan`, `retrieved_chunks`, `calculated_metrics`, `iteration_count`, `tool_call_count`, and `hitl_required`.
- **Iteration & Cost Guardrails**: Every node increment checks `iteration_count <= 10` and `total_cost <= $0.50`. If limits are approached, the graph transitions to the `synthesize` node immediately.

### 5. How Does It Scale?
- State objects are small and serialized to Redis checkpoints.
- Individual agent nodes run concurrently within the async event loop where possible (e.g., retrieving market data while querying SEC filings in parallel).

### 6. What Happens When It Fails?
- If an agent node encounters an unhandled tool exception or model timeout, the error is written to `state["errors"]`. The Orchestrator inspects the error and attempts a fallback strategy or cleanly exits with a partial analysis.

### 7. How Is It Secured?
- **Tool Allowlisting by Role**: The Quantitative Risk Assessor can only invoke mathematical tools; it cannot call database modification tools.
- **Excessive Agency Gate**: The agent cannot execute destructive or high-consequence portfolio trades autonomously. Any action with financial consequence triggers our **Human-in-the-Loop (HITL)** interruption.

### 8. How Is It Monitored?
- Metrics: `agent.execution_time_ms`, `agent.iterations_count`, `agent.tool_calls_count`, `agent.success_rate`, `agent.failure_rate`.
- OpenTelemetry: Every agent iteration emits a span with the agent name, input prompt tokens, output tokens, and selected tools.

### 9. What Are the Trade-offs?
- **Latency**: Multi-agent handoffs add latency (typically 3–8 seconds for an end-to-end multi-step workflow) compared to 1–2 seconds for a single LLM call. In financial risk analysis, correctness and auditability completely supersede raw sub-second speed.

---

## 2. Spoken Interview Responses

### Interviewer: "How do you prevent an agent from getting stuck in an infinite loop?"
**Spoken Response:**
"In autonomous agent systems, infinite loops are a critical financial and operational risk—an unconstrained agent can burn thousands of dollars in LLM API calls in minutes.

We enforce **Triple-Lock Loop Prevention** in `src/agents/state.py` and `src/security/guards.py`:
1. **Deterministic State Counter**: The LangGraph state machine maintains an immutable `iteration_count`. At the start of every single node execution, a conditional routing function checks `if state['iteration_count'] >= MAX_ITERATIONS (default 10)`. If reached, it forces an immediate edge transition to the `synthesize_and_exit` node, bypassing all other agent nodes.
2. **Tool Repetition Detection**: We track the history of tool calls and parameter hashes. If an agent calls the exact same tool with identical parameters twice in a row without state progress, the tool interceptor raises a `DuplicateToolCallException`, forcing the agent to reflect and change strategy.
3. **Hard Timeout & Token Budget**: Every LangGraph run is bound by an `asyncio.wait_for(timeout=30.0)` wrapper and a maximum token expenditure limit (e.g., 20,000 tokens). If either threshold is breached, execution terminates gracefully, returning all intermediate findings collected so far."

### Interviewer: "How does the agent decide which tool to call, and how do you guarantee it passes the right parameters?"
**Spoken Response:**
"We use model-native structured tool calling (via Anthropic Claude 3.5 Sonnet's `tools` API in AWS Bedrock), backed by strict Pydantic schemas defined in our Model Context Protocol (MCP) registry.

Here is the exact mechanism:
1. When the Risk Assessor agent node is activated, only the specific subset of tools registered for the Risk Assessor role are serialized into the API payload. We do not expose all platform tools to all agents.
2. Each tool has a Pydantic schema with strict field descriptions, types, and constraints (e.g., `confidence_interval: float = Field(ge=0.90, le=0.99)`).
3. The model returns a structured `tool_use` block containing the tool name and JSON parameters.
4. Before calling the actual calculation engine, our MCP Gateway validates the payload against the Pydantic model. If the model hallucinates an invalid parameter type or an out-of-range value, validation fails locally. The error is returned to the model as a `tool_result` with the validation error message, allowing the model to self-correct on the next iteration without crashing the runtime."
