# ADR-006: Model Context Protocol (MCP) for Controlled Financial Tool Integration

## Status
Accepted

## Context
Financial copilots require integration with external financial tools: SEC EDGAR filing endpoints, live market quotes, bond yield feeds, and quantitative risk calculators. Directly binding proprietary APIs into agent prompts causes vendor lock-in, insecure tool execution, and complex testing.

## Decision
We adopt the **Model Context Protocol (MCP)** standard for controlled tool integration.

## Why This Technology Was Selected
1. **Standardized Tool Discovery & Schema Negotiation**: MCP establishes an open, standardized JSON-RPC protocol for declaring tools, schemas, and resource access. Agents discover tools dynamically without hardcoded glue code.
2. **Security Sandboxing & Access Control**: MCP servers run in isolated processes or micro-containers. The copilot communicates via controlled MCP RPC boundaries, preventing untrusted tool code from accessing the core database or application memory.
3. **Decoupled Evolution**: SEC Edgar scrapers or live market data feeds can be upgraded, patched, or swapped without modifying the core LangGraph agent logic.

## Alternatives Considered
- **Direct Python Function Calling in LangChain**: Tightly couples tool implementations to the agent codebase and complicates running tools in isolated security boundaries.
