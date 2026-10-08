# 12 — GenAI Evaluation, Regression Testing & Quality Benchmarking

## 1. Component Analysis (9 Core Dimensions)

### 1. What Problem Does It Solve?
Deploying prompt changes, new embedding models, or agent modifications to production without systematic evaluation is reckless. Without automated benchmarking, a prompt tweak intended to improve clarity might silently degrade Context Recall, increase hallucination rates, or introduce cross-tenant leakage.

### 2. Why Did We Choose This Evaluation Platform?
We engineered an in-house **Automated GenAI Evaluation Platform** (`src/evaluation/`) operating across three critical domains:
- **RAG Quality Evaluation**: Measures Context Precision, Context Recall, Faithfulness, Answer Relevancy, Precision@K, Recall@K, Mean Reciprocal Rank (MRR), and Normalized Discounted Cumulative Gain (NDCG).
- **Agent Trajectory Evaluation**: Evaluates Task Success, Tool Selection Accuracy, Trajectory Correctness, Unnecessary Tool Calls, Execution Latency, and Token Cost.
- **Safety & Compliance Evaluation**: Benchmarks Hallucination Rate, Prompt Injection Defense, Unauthorized Tool Invocation, Cross-Tenant Leakage, and Unsupported Claims.
- **Automated CI Regression Gate**: Executes in CI pipelines (`src/evaluation/ci_runner.py`), automatically failing builds if quality drops beyond defined thresholds.

### 3. What Alternatives Were Considered?
- **Ragas / TruLens (Direct Integration)**: Good for basic RAG metrics, but lacked support for multi-agent trajectory validation, tool-calling correctness, and strict cross-tenant leakage checks.
- **Manual Human Spot-Checking**: Slow, subjective, expensive, and completely incapable of running in continuous integration pipelines on every pull request.

### 4. How Does It Work Internally?
```
CI Pipeline / Regression Test Trigger
     │
     ▼
[Evaluation Dataset Loader] (Golden Questions, Expected Sources, Expected Tool Calls)
     │
     ├── 1. Execute RAG Evaluation Suite
     │       ├── Context Precision & Recall (Ground Truth vs Retrieved Chunks)
     │       ├── Faithfulness (Answer claims supported by Context)
     │       └── Ranking Metrics (MRR, NDCG@5, Precision@3)
     │
     ├── 2. Execute Agent Evaluation Suite
     │       ├── Tool Selection Accuracy (Did agent choose `portfolio_risk_calculator`?)
     │       ├── Trajectory Correctness (Optimal path vs extraneous loops)
     │       └── Efficiency (Token usage & Cost USD within budget)
     │
     ├── 3. Execute Safety Evaluation Suite
     │       ├── Prompt Injection Tests (Direct jailbreaks & indirect text payloads)
     │       └── Cross-Tenant Leakage Tests (Attempting to query other tenant data)
     │
     ▼
[Regression Gate Checker] (`ci_runner.py`)
     │
     ├─► All Metrics >= Thresholds? ──► PASS (Merge Allowed)
     │
     └─► Any Metric < Threshold?     ──► FAIL CI (Exit Code 1, Block Deployment)
```

### 5. How Does It Scale?
- Evaluation runs utilize synthetic golden datasets executed concurrently against async mock or Bedrock providers.
- Test suites run in CI within ~45–60 seconds.

### 6. What Happens When It Fails?
- If a prompt edit or code change causes Faithfulness to drop below 0.85 or Tool Selection Accuracy below 0.90, `ci_runner.py` exits with status code 1, generating a markdown regression report that blocks the pull request from merging.

### 7. How Is It Secured?
- Evaluation golden datasets are version-controlled in the repository and contain sanitized, public SEC filing samples without proprietary client PII.

### 8. How Is It Monitored?
- Evaluation scores are exported as JSON artifacts and tracked over time across commits.

### 9. What Are the Trade-offs?
- **LLM-as-a-Judge API Cost**: Using an evaluator model to score Faithfulness and Relevancy incurs small API costs during CI runs. We mitigate this by using fast evaluation models (Claude 3.5 Haiku) for CI gates.

---

## 2. Spoken Interview Responses

### Interviewer: "How do you evaluate hallucinations in a financial RAG system?"
**Spoken Response:**
"In financial research, calculating hallucination rates requires decomposing the problem into **Faithfulness** and **Citation Grounding**:

In our `RAGEvaluator` (`src/evaluation/rag_evaluator.py`), we implement an algorithmic two-step verification:
1. **Claim Extraction**: The answer is parsed into atomic factual assertions (e.g., *'Company X's long-term debt increased by 12% in FY2023'*).
2. **Context Verification**: Each atomic claim is evaluated against the exact retrieved chunks provided in the prompt context.
3. **Faithfulness Score**: We compute the ratio: `Faithfulness = (Supported Claims) / (Total Claims)`. A score of 1.0 means 100% of the assertions are backed by the retrieved text.
4. **Citation Grounding**: In addition, our security guardrail checks every cited chunk ID using SHA256 chunk hash lookups. If the model cites a source chunk that does not exist or attributes a claim to the wrong document, the hallucination score drops to zero, and the build fails. All metrics come from deterministic execution against golden datasets—we never report synthetic or guessed scores."

### Interviewer: "How do you evaluate agent performance and trajectory correctness?"
**Spoken Response:**
"Evaluating an agent is much more complex than evaluating a single prompt because an agent executes a multi-step path of tool calls and intermediate reflections.

In our `AgentEvaluator` (`src/evaluation/agent_evaluator.py`), we score four specific dimensions:
1. **Task Success**: Did the final output correctly answer the prompt and fulfill the financial mandate?
2. **Tool Selection Accuracy**: Across each step in the trajectory, did the agent select the expected tool from its allowlist (e.g., choosing `portfolio_risk_calculator` for VaR calculations rather than fabricating a formula)?
3. **Trajectory Correctness & Unnecessary Tool Calls**: We compare the agent's actual execution path against an optimal golden trajectory. If an agent takes eight iterations when the optimal path requires three, or calls irrelevant tools repeatedly, the trajectory score penalizes the run.
4. **Token & Cost Efficiency**: We measure the exact token consumption and latency of the run. If a model update causes token usage to surge by 50% for the same task, the regression gate flags it before that model change can hit production."
