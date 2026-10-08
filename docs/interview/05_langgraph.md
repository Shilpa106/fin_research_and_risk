# 05 — LangGraph State Machine & Orchestration Engine

## 1. Component Analysis (9 Core Dimensions)

### 1. What Problem Does It Solve?
Standard LLM agent frameworks treat agent workflows as black-box loops. In enterprise financial systems, workflows must be **cyclic state machines** with deterministic branching, durable state persistence across hours or days, and the ability to halt execution for human approval before resuming without losing context.

### 2. Why Did We Choose LangGraph?
We selected **LangGraph** because it models workflows as explicit graphs of nodes and conditional edges governed by a typed state schema:
- **Cyclic Graph Support**: Enables iterative research, reflection, and refinement loops that are impossible in pure acyclic DAG runners (like Airflow).
- **First-Class Checkpointing**: Serializes graph state at every step to a persistent checkpointer (PostgreSQL/Redis), enabling instant recovery from process crashes.
- **Native Human-in-the-Loop Interruption**: Allows arbitrary nodes (e.g., `risk_approval`) to pause execution, wait for external human review, and resume seamlessly.
- **Time-Travel Debugging**: Allows engineers to inspect, replay, or fork previous execution states for compliance audits.

### 3. What Alternatives Were Considered?
- **LangChain `AgentExecutor`**: Deprecated by LangChain itself; treated agent loops as an opaque while-loop with no state visibility, no persistent checkpoints, and zero support for pausing for human approval.
- **LlamaIndex Workflows**: Capable, but lacked the enterprise checkpointing ecosystem and mature state-machine graph semantics provided by LangGraph.
- **Custom Python State Machine**: High maintenance burden; would require reinventing state serialization, graph compilers, conditional routers, and streaming hooks from scratch.

### 4. How Does It Work Internally?
```python
# Conceptual Architecture implemented in src/agents/graph.py
builder = StateGraph(CopilotState)

# 1. Define Nodes
builder.add_node("orchestrator", orchestrator_node)
builder.add_node("research_analyst", research_node)
builder.add_node("risk_assessor", risk_node)
builder.add_node("hitl_gate", hitl_gate_node)
builder.add_node("synthesizer", synthesizer_node)

# 2. Define Edges and Conditional Routing
builder.set_entry_point("orchestrator")
builder.add_conditional_edges(
    "orchestrator",
    route_by_intent,
    {
        "research": "research_analyst",
        "risk": "risk_assessor",
        "synthesize": "synthesizer"
    }
)
builder.add_edge("research_analyst", "orchestrator")
builder.add_conditional_edges(
    "risk_assessor",
    check_risk_threshold,
    {
        "exceeds_threshold": "hitl_gate",
        "acceptable": "orchestrator"
    }
)
builder.add_edge("hitl_gate", "synthesizer")
builder.add_edge("synthesizer", END)

# 3. Compile with Checkpointer
graph = builder.compile(checkpointer=redis_checkpointer, interrupt_before=["hitl_gate"])
```

### 5. How Does It Scale?
- Graph state is lightweight JSON.
- Checkpoints are saved asynchronously to ElastiCache Redis (TTL = 24 hours) or Aurora PostgreSQL for long-running audit archives.
- Web nodes running ECS Fargate remain completely stateless; any available worker can pick up and resume a paused execution using the `thread_id`.

### 6. What Happens When It Fails?
- If a node throws an unhandled exception or worker process terminates, the checkpoint engine preserves the exact state of the last completed node. When the request is retried, LangGraph resumes from the last healthy checkpoint rather than restarting from step zero.

### 7. How Is It Secured?
- State schemas strictly sanitize inputs. Tenant isolation claims (`tenant_id`, `user_id`) in the state cannot be overwritten by LLM tool outputs.

### 8. How Is It Monitored?
- Custom OpenTelemetry hooks instrument each graph transition. Every node entry and exit generates an OTel span recording node name, state delta, latency, and token consumption.

### 9. What Are the Trade-offs?
- **Schema Rigidity**: Updating the typed state schema requires careful backward-compatibility handling for existing in-flight checkpoints stored in the database.

---

## 2. Spoken Interview Responses

### Interviewer: "Why LangGraph instead of LangChain?"
**Spoken Response:**
"When developers say 'LangChain', they usually mean the legacy `AgentExecutor` or standard LCEL chains. LCEL chains are strictly Directed Acyclic Graphs (DAGs)—they run linearly from prompt to model to parser, but real financial research is fundamentally **cyclic**. An analyst reads a 10-K, realizes they need a debt maturity schedule, runs a tool, encounters an ambiguity, and must loop back to research.

The legacy `AgentExecutor` supported loops, but it was a black box. You couldn't control the transitions, you couldn't persist state mid-loop, and you couldn't pause execution for three hours while a Chief Risk Officer reviewed a trade.

LangGraph solves this by treating agent workflows as **explicit state-machine graphs**:
1. **Control and Determinism**: We define the exact nodes and conditional edges. The model doesn't just wander freely; our code dictates which agent can transition to which next step based on deterministic conditional functions.
2. **First-Class Persistence**: LangGraph serializes state into a checkpointer at every single node transition. If a cloud server dies mid-execution, we resume from that exact node.
3. **True Human-in-the-Loop**: We can place an `interrupt_before=['hitl_gate']` directive on any node. The graph halts, saves its state to PostgreSQL, returns a task ID to the user, and waits. When the human approves via an API endpoint, the graph resumes with the exact context intact."

### Interviewer: "How do you implement Human-in-the-Loop (HITL) in LangGraph without holding open long-lived HTTP connections?"
**Spoken Response:**
"Holding open an HTTP connection for a human approval is an anti-pattern that causes gateway timeouts and socket leaks. Here is our asynchronous architecture:

1. When the Risk Assessor determines that a calculated portfolio variance exceeds the tenant's risk policy (e.g., VaR > 5%), it transitions to the `hitl_gate` node.
2. The LangGraph compilation includes `interrupt_before=['hitl_gate']`. The graph executes up to the gate and pauses.
3. The checkpointer automatically persists the graph's entire execution memory to PostgreSQL/Redis under a unique `thread_id`.
4. Our API service inserts a corresponding `HITLTask` record into the database with status `PENDING`, captures the task metadata, and immediately returns an HTTP 202 Accepted response with the `task_id` to the client.
5. Hours or days later, an authorized compliance officer reviews the task in the dashboard and clicks 'Approve'. This calls `POST /api/v1/hitl/tasks/{id}/approve`.
6. The HITL service updates the database record to `APPROVED`, loads the saved checkpoint via `graph.get_state(config={'configurable': {'thread_id': thread_id}})`, updates the state with the human's approval payload, and invokes `graph.invoke(None, config)`.
7. LangGraph resumes execution right from the `hitl_gate` node, runs the synthesizer, and delivers the final report. The web layer remains completely stateless and decoupled throughout."
