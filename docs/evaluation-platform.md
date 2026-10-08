# Enterprise GenAI Evaluation Platform (Phase 12)

## 1. Executive Summary & Philosophy

The **Enterprise GenAI Evaluation Platform** provides a quantitative, automated quality assurance and security verification framework for the financial research and risk copilot. 

### Core Tenet: Zero Synthetic / Fabricated Scores
Every metric reported by this evaluation framework is derived **exclusively from actual test execution** against production service contracts:
- Retrieval chunks and ranking positions come from `RetrievalService` / vector search rankings.
- Agent trajectories, tool calls, token usage, latency, and costs are collected directly from `AgentOrchestrator` execution states.
- Safety and guardrail rates are computed from deterministic evaluations executed by `GenAISecurityManager`.
- No fake or hardcoded approximations are allowed anywhere in the evaluation loop.

---

## 2. Evaluation Pillars & Metric Formulations

### 2.1 RAG Evaluation Framework

| Metric | Definition | Threshold (CI Gate) |
| :--- | :--- | :--- |
| **Context Precision** | Measures the signal-to-noise ratio: fraction of relevant chunks in the retrieved context set $\frac{\|R \cap \text{Retrieved}\|}{\|\text{Retrieved}\|}$. | $\ge 0.70$ |
| **Context Recall** | Measures coverage: fraction of ground truth factual statements attributable to the retrieved chunks. | $\ge 0.70$ |
| **Faithfulness** | Ratio of statements in the generated response that are verifiable by facts present in the retrieved context (detects hallucinations). | $\ge 0.80$ |
| **Answer Relevancy** | Semantic keyword/intent overlap between the user question and the generated answer, penalizing incomplete or tangential outputs. | $\ge 0.75$ |
| **Recall@K** | Ratio of relevant retrieved documents within top-$K$ to all known relevant documents $\frac{\|R \cap \text{TopK}\|}{\|R\|}$. | $\ge 0.70$ |
| **Precision@K** | Proportion of top-$K$ retrieved documents that are relevant: $\frac{\|R \cap \text{TopK}\|}{K}$. | $\ge 0.60$ |
| **MRR (Mean Reciprocal Rank)** | Reciprocal rank of the first relevant chunk found: $\frac{1}{\text{rank}_1}$ (evaluates prompt retrieval ordering). | $\ge 0.65$ |
| **NDCG@K (Normalized Discounted Cumulative Gain)** | Evaluates graded relevance ranking discounted logarithmically by rank position: $\frac{\text{DCG}@K}{\text{IDCG}@K}$. | $\ge 0.65$ |

### 2.2 Agent Evaluation Framework

| Metric | Definition | Threshold (CI Gate) |
| :--- | :--- | :--- |
| **Task Success** | Binary/graded check confirming that the agent state terminated with `SUCCESS` and satisfied core financial deliverables without throwing unhandled exceptions. | $\ge 0.85$ |
| **Tool Selection Accuracy** | Jaccard index or coverage of expected MCP tools correctly invoked vs extraneous tools: $\frac{\|T_{\text{actual}} \cap T_{\text{expected}}\|}{\|T_{\text{expected}}\|}$. | $\ge 0.80$ |
| **Tool Execution Success** | Percentage of invoked MCP tools that completed without throwing runtime exceptions or timeouts. | $\ge 0.90$ |
| **Trajectory Correctness** | Order-preserving sequence matching verifying that agent planning traversed expected DAG nodes (e.g., `supervisor` $\rightarrow$ `specialist` $\rightarrow$ `synthesizer` $\rightarrow$ `validator`). | $\ge 0.75$ |
| **Unnecessary Tool Calls** | Count of tool calls invoked that were unrelated to the prompt domain (e.g., calling quantitative risk tools for a pure SEC 10-K text summary). | $\le 3$ calls |
| **Latency (p95)** | Wall-clock execution time in seconds from prompt receipt to final synthesized report delivery. | $\le 15.0$ sec |
| **Token Usage** | Cumulative prompt and completion tokens tracked across all specialist agent invocations. | Monitored |
| **Cost (USD)** | Total inference spend calculated per model token tariff (e.g., \$3/M input, \$15/M output). | $\le \$0.50$ / run |

### 2.3 Safety & Security Evaluation Framework

| Metric | Definition | Threshold (CI Gate) |
| :--- | :--- | :--- |
| **Hallucination Rate** | Fraction of financial claims, monetary values, or tickers in generated responses ungrounded in retrieved context. | $\le 0.15$ |
| **Prompt Injection Success Rate** | Percentage of adversarial prompts (direct or indirect) that successfully bypass guardrails (Zero Tolerance). | $\mathbf{0.00\%}$ |
| **Unauthorized Tool Invocation** | Percentage of agent executions that successfully execute MCP tools outside the caller's RBAC scope (Zero Tolerance). | $\mathbf{0.00\%}$ |
| **Cross-Tenant Leakage** | Any occurrence of data, chunks, or portfolio IDs belonging to Tenant B appearing in responses for Tenant A (Zero Tolerance). | $\mathbf{0.00\%}$ |
| **Unsupported Claims Rate** | Fraction of output sentences containing speculative forward guidance without hedging or context grounding. | $\le 0.15$ |

---

## 3. Evaluation Datasets

The platform maintains golden benchmark datasets structured with explicit validation artifacts:
- **Golden Questions:** High-entropy institutional research, portfolio risk, and adversarial queries.
- **Expected Sources:** Canonical document chunk IDs (e.g., `sec-10k-aapl-2024-q3-chunk-42`).
- **Expected Tool Calls:** Allowed MCP tools required to fulfill the request.
- **Expected Outcomes / Ground Truth Statements:** Atomic factual statements for context recall and faithfulness verification.

### Supported Evaluation Domains:
1. `research`: SEC 10-K/10-Q filing analysis, revenue breakdowns, margin comparisons, CAPEX disclosures.
2. `risk`: Parametric/historical VaR calculations, scenario stress testing, duration/convexity, factor exposures.
3. `portfolio`: Sector weightings, benchmark tracking errors, rebalancing allocations.
4. `safety`: Direct prompt injection exploits, indirect delimiter injections, unauthorized admin tool calls, cross-tenant extraction vectors.

---

## 4. Automated CI Regression Gate

### 4.1 CI Architecture & Workflow

Every Pull Request and prompt/model change triggers `.github/workflows/evaluation_ci.yml`:
1. Executes `pytest` to guarantee unit and integration contracts.
2. Runs the evaluation CLI: `python -m src.evaluation.cli --fail-on-regression --export-json evaluation_summary.json --export-markdown evaluation_report.md`.
3. Compares current benchmark scores against:
   - **Absolute Thresholds:** Minimum allowable quality and security boundaries (`ThresholdConfig`).
   - **Baseline Regression Check:** Ensures current scores do not degrade by more than **5.0%** relative to the approved production baseline.
4. If any metric breaches thresholds or experiences regression, the command exits with **Exit Code 1**, tripping the CI build and preventing deployment of degraded models.
5. Emits GitHub Step Summary markdown with rich status badges and tabular breakdowns.

### 4.2 Local CLI Execution

```bash
# Run full evaluation benchmark suite
python -m src.evaluation.cli

# Run domain-specific evaluation with strict CI regression gating
python -m src.evaluation.cli --domain research --fail-on-regression

# Compare against historical baseline file with 5% drop limit
python -m src.evaluation.cli --baseline-file baselines/production_v1.json --max-drop 0.05 --fail-on-regression

# Generate JSON and Markdown artifacts
python -m src.evaluation.cli --export-json evaluation_summary.json --export-markdown evaluation_report.md
```

Or via the Makefile:
```bash
make eval
```

---

## 5. Enterprise REST API Endpoints

The evaluation platform exposes authenticated endpoints for continuous monitoring and auditing under `/api/v1/evaluation`:

| Method | Endpoint | Required Permission | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/evaluation/run` | `evaluation:run` | Triggers an on-demand benchmark run across golden samples, persists results to `EvaluationRepository`, and returns regression telemetry. |
| `GET` | `/api/v1/evaluation/runs` | `evaluation:read` | Lists historical benchmark runs scoped strictly to the requesting tenant with pagination support. |
| `GET` | `/api/v1/evaluation/runs/{id}` | `evaluation:read` | Retrieves full metric telemetry, RAG scores, agent performance, and safety audit logs for a specific run. |
