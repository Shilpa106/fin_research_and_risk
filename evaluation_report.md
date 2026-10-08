# GenAI Quality & Safety Evaluation Report — PASSED ✅

**Dataset:** `institutional-financial-eval-v1` | **Samples Tested:** `7` | **Timestamp:** `2026-10-08T08:51:54.630798`

### 1. RAG Evaluation Metrics
| Metric | Current | Baseline | Minimum Threshold | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Context Precision** | `1.0000` | `N/A` | `0.7000` | ✅ |
| **Context Recall** | `1.0000` | `N/A` | `0.7000` | ✅ |
| **Faithfulness** | `0.9286` | `N/A` | `0.8000` | ✅ |
| **Answer Relevancy** | `0.7857` | `N/A` | `0.7500` | ✅ |
| **Recall@5** | `1.0000` | `N/A` | `0.7000` | ✅ |
| **Precision@5** | `1.0000` | `N/A` | `0.6000` | ✅ |
| **MRR** | `1.0000` | `N/A` | `0.6500` | ✅ |
| **NDCG@5** | `1.0000` | `N/A` | `0.6500` | ✅ |

### 2. Multi-Agent Reasoning & Execution Telemetry
| Metric | Current | Baseline | Target Standard | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Task Success** | `1.0000` | `N/A` | `>= 0.8500` | ✅ |
| **Tool Selection Accuracy** | `1.0000` | `N/A` | `>= 0.8000` | ✅ |
| **Tool Execution Success** | `1.0000` | `N/A` | `>= 0.9000` | ✅ |
| **Trajectory Correctness** | `1.0000` | `N/A` | `>= 0.7500` | ✅ |
| **Unnecessary Tool Calls** | `0` | `N/A` | `<= 3` | ✅ |
| **Latency (s)** | `0.008s` | `N/A` | `<= 15.0s` | ✅ |
| **Token Usage** | `4790` | `N/A` | `Telemetry` | ℹ️ |
| **Cost (USD)** | `$0.0116` | `N/A` | `<= $0.50` | ✅ |

### 3. AI Safety, Guardrails & Multi-Tenant Isolation
| Metric | Current | Baseline | Maximum Allowance | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Hallucination Rate** | `0.0000` | `N/A` | `<= 0.1500` | ✅ |
| **Prompt Injection Success** | `0.0000` | `N/A` | `0.0000 (Zero Tolerance)` | ✅ |
| **Unauthorized Tool Invocation** | `0.0000` | `N/A` | `0.0000 (Zero Tolerance)` | ✅ |
| **Cross-Tenant Leakage** | `0.0000` | `N/A` | `0.0000 (Zero Tolerance)` | ✅ |
| **Unsupported Claims Rate** | `0.0000` | `N/A` | `<= 0.1500` | ✅ |
