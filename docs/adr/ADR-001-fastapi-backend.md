# ADR-001: Selection of FastAPI for API Gateway and Service Tier

## Status
Accepted

## Context
The platform must sustain a peak load of 10,000 API requests/second with 100,000 concurrent active users. The majority of requests involve high-concurrency async I/O: Redis cache checks, PostgreSQL queries, OpenSearch hybrid queries, and streaming AI responses.

## Decision
We select **FastAPI** running on Uvicorn with `uvloop` as the primary API framework.

## Why This Technology Was Selected
1. **Asynchronous Non-Blocking Concurrency**: Built natively on Starlette and `asyncio`, FastAPI handles thousands of concurrent socket connections per process without the memory bloat of synchronous multi-threaded WSGI frameworks (e.g., Flask or standard Django).
2. **Native OpenAPI & Pydantic Schema Validation**: Request/response contracts are strictly validated at runtime with Pydantic v2 (Rust-backed core), minimizing payload parsing overhead and automatically producing institutional OpenAPI 3.1 specifications.
3. **High-Performance Streaming**: Native async generator support enables Server-Sent Events (SSE) and WebSocket streams for real-time token streaming from LLM and agent reasoning traces.
4. **Dependency Injection**: FastAPI's built-in DI system enables clean separation of concerns, multi-tenant session isolation, and pluggable local mock vs. production cloud providers.

## Alternatives Considered
- **Flask / Django (WSGI)**: Poor concurrency under high async I/O; requires heavy thread/process pools that degrade memory efficiency under 100K CCU.
- **Node.js (NestJS / Express)**: Excellent concurrency, but separates the API layer from the Python GenAI ecosystem (LangGraph, PyTorch, NumPy, Pandas, Scipy), introducing serialization overhead and dual-language maintenance.
- **Go / Rust**: Maximum raw throughput, but lacks native first-class integration with the Python AI/ML ecosystem. FastAPI provides the optimal balance of Python AI interoperability and high-throughput async I/O.
