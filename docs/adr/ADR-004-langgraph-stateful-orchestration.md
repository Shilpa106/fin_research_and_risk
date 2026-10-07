# ADR-004: LangGraph for Stateful Multi-Agent Orchestration & HITL Gates

## Status
Accepted

## Context
Financial research and risk analysis require multi-step, cyclical agent workflows (query routing, document retrieval, financial model execution, cross-verification, and compliance validation). Furthermore, regulatory mandates require Human-in-the-Loop (HITL) gates to pause execution when risk thresholds (e.g., VaR > 5% or concentration limits) are exceeded, awaiting senior risk officer sign-off before report publication.

## Decision
We select **LangGraph** as the multi-agent stateful workflow orchestrator.

## Why This Technology Was Selected
1. **Cyclical Graph Execution with First-Class State**: Unlike linear DAG chains (LangChain standard chains), financial research requires loops (e.g. if retrieval relevance is below threshold, rewrite query and re-retrieve). LangGraph models agents as explicit state machines with typed state transitions.
2. **Native Human-in-the-Loop (HITL) Interrupts**: LangGraph supports pausing execution at specific nodes (`interrupt_before=["hitl_review_gate"]`), checkpointing the entire thread state to durable storage (PostgreSQL/Redis), and resuming execution with new input when a risk officer approves or modifies the report.
3. **Durable Persistence & Time Travel**: Every step creates a verifiable checkpoint, enabling compliance auditability and retrospective review of agent decision trees.

## Alternatives Considered
- **AutoGen**: Good for open-ended multi-agent conversation, but lacks strict institutional state machine guarantees, deterministic checkpointing, and enterprise interrupt controls.
- **CrewAI**: Higher-level abstraction, but harder to customize for low-latency production API streaming and strict state-level database checkpointing.
- **Custom In-House Finite State Machine**: Reinventing state persistence, branching, and streaming would create unnecessary engineering debt.
