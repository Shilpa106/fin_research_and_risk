# ADR-007: LangGraph for Stateful Multi-Agent Orchestration & HITL Gates

## Status
Accepted

## Context
Financial research and portfolio risk analysis require multi-step, cyclical agent workflows (query classification, filing retrieval, quantitative modeling, compliance review, and report synthesis). Critical institutional policies require pausing agent execution at **Human-in-the-Loop (HITL)** gates when Value-at-Risk limits or regulatory flags are tripped, checkpointing state durably, and resuming execution upon Senior Risk Officer sign-off.

---

## Technical Evaluation (The 9 Architectural Dimensions)

### 1. Why this technology?
LangGraph models agent workflows as explicit, cyclical **StateGraphs** with typed state schemas (`CopilotState`). It natively supports cyclical loops (e.g. query rewriting if initial retrieval relevance is low), conditional edge branching, durable multi-tenant checkpointing, and native `interrupt()` mechanisms for Human-In-The-Loop review gates.

### 2. What alternatives were considered?
- **LangChain Standard Chains / LCEL (Linear DAGs)**
- **AutoGen (Microsoft)**
- **CrewAI**
- **Temporal / AWS Step Functions with custom code**

### 3. Why were they rejected?
- **LangChain Standard Chains**: Strictly directed acyclic graphs (DAGs). Cannot handle iterative loops, reflection, self-correction, or stateful human interruptions.
- **AutoGen**: Designed primarily for unstructured multi-agent conversation simulations; lacks strict institutional state machine schema guarantees, deterministic checkpointing, and native interrupt semantics.
- **CrewAI**: Higher-level abstraction with rigid role-playing metaphors, making fine-grained state checkpointing to PostgreSQL and streaming token emissions difficult to control.
- **Temporal / Step Functions**: Outstanding general-purpose orchestrators, but introduce significant latency overhead (several hundred milliseconds per state transition) and require heavy external orchestrator infrastructure compared to native in-process LangGraph compilation.

### 4. What happens at 10M users?
Agent workflows are stateless in container memory between execution turns. State is externalized to durable checkpointers in PostgreSQL and Redis. At 10M users, LangGraph scales horizontally across all ECS tasks without thread starvation.

### 5. What happens if the component fails?
- Because every node execution creates a durable state checkpoint in PostgreSQL, an unexpected container crash or restart does not lose analyst work.
- The workflow can be re-instantiated on any healthy container simply by loading the last saved checkpoint ID from the database (`thread_id`).

### 6. How does it scale?
Scales linearly with container fleet size. State serialization overhead is negligible (< 1ms per node transition for JSON state dictionaries).

### 7. What is the operational cost?
Open-source library (zero software licensing fees). Checkpoint storage in Aurora PostgreSQL consumes ~$50/month in database storage.

### 8. What is the AWS production equivalent?
**LangGraph Runtime** running on AWS ECS with durable checkpoints persisted in **Amazon Aurora PostgreSQL**.

### 9. What is the local-development equivalent?
LangGraph running in-process with `MemorySaver` in-memory checkpointer for ultra-fast local unit testing.
