"""
Institutional GenAI Evaluation & Regression Detection CLI.
Runs golden benchmark evaluation suites against RAG, Multi-Agent, and Safety platform pillars.
Enforces automated CI/CD gating by checking quality against configurable thresholds and baseline runs.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from ..domain.exceptions import EvaluationRegressionException
from .datasets import (
    GoldenDataset,
    load_golden_dataset_from_json,
    load_golden_evaluation_dataset,
)
from .models import EvaluationSummary, ThresholdConfig
from .regression import RegressionDetector
from .runner import EvaluationRunner

logger = logging.getLogger("enterprise_copilot.evaluation.cli")

# Ensure UTF-8 console support across Windows CI runners and terminals
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enterprise GenAI Evaluation Platform & CI Quality Regression Gate",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="institutional-financial-eval-v1",
        help="Name of built-in benchmark dataset or path to dataset JSON file",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        choices=["research", "risk", "portfolio", "safety"],
        help="Filter evaluation to specific analytical or security domain",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="claude-3-5-sonnet",
        help="Model identifier under evaluation",
    )
    parser.add_argument(
        "--thresholds",
        type=str,
        default=None,
        help="Path to custom JSON file containing ThresholdConfig overrides",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        help="Path to previous approved EvaluationSummary JSON file for relative drop comparison",
    )
    parser.add_argument(
        "--output",
        "--export-json",
        dest="output",
        type=str,
        default="evaluation_summary.json",
        help="Path to output evaluated summary JSON file",
    )
    parser.add_argument(
        "--markdown-report",
        "--export-markdown",
        dest="markdown_report",
        type=str,
        default="evaluation_report.md",
        help="Path to output markdown report file for CI/CD summaries",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        default=True,
        help="Exit with non-zero status code if quality drops below configured thresholds or baseline",
    )
    parser.add_argument(
        "--no-fail-on-regression",
        dest="fail_on_regression",
        action="store_false",
        help="Do not fail process even if quality drops below thresholds",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Rank cutoff K for retrieval metrics (Recall@K, NDCG@K)",
    )
    parser.add_argument(
        "--max-drop-pct",
        type=float,
        default=0.05,
        help="Maximum allowable percentage drop vs baseline before tripping CI regression gate (0.05 = 5%%)",
    )
    return parser.parse_args()


async def run_cli() -> int:
    args = parse_args()

    # 1. Load Dataset
    if os.path.isfile(args.dataset):
        print(f"[EVAL-CI] Loading dataset from file: {args.dataset}")
        dataset = load_golden_dataset_from_json(args.dataset)
    else:
        print(f"[EVAL-CI] Loading built-in dataset: {args.dataset} (domain filter: {args.domain or 'all'})")
        dataset = load_golden_evaluation_dataset(name=args.dataset, domain=args.domain)

    print(f"[EVAL-CI] Benchmark dataset loaded: '{dataset.name}' ({len(dataset.samples)} samples)")

    # 2. Load Threshold Configuration
    if args.thresholds and os.path.isfile(args.thresholds):
        print(f"[EVAL-CI] Loading quality thresholds from: {args.thresholds}")
        with open(args.thresholds, encoding="utf-8") as f:
            thresh_dict = json.load(f)
        thresholds = ThresholdConfig(**thresh_dict)
    else:
        thresholds = ThresholdConfig()

    # 3. Load Baseline if provided
    baseline: EvaluationSummary | None = None
    if args.baseline and os.path.isfile(args.baseline):
        print(f"[EVAL-CI] Loading previous production baseline from: {args.baseline}")
        with open(args.baseline, encoding="utf-8") as f:
            base_data = json.load(f)
        # Reconstruct models from dict
        from .models import AgentMetrics, RAGMetrics, SafetyMetrics
        baseline = EvaluationSummary(
            dataset_name=base_data.get("dataset_name", "baseline"),
            total_samples=base_data.get("total_samples", 0),
            rag_metrics=RAGMetrics(**base_data["rag"]),
            agent_metrics=AgentMetrics(**base_data["agent"]),
            safety_metrics=SafetyMetrics(**base_data["safety"]),
            timestamp=datetime.fromisoformat(base_data.get("timestamp", datetime.utcnow().isoformat())),
        )

    # 4. Execute Benchmark Suite
    print(f"[EVAL-CI] Executing evaluation suite against actual platform services (Model: {args.model})...")
    runner = EvaluationRunner()
    current_summary = await runner.run_evaluation_suite(
        dataset=dataset,
        model_id=args.model,
        k=args.k,
    )

    # 5. Check for Regressions
    detector = RegressionDetector(thresholds=thresholds)
    report = detector.check_regression(
        current=current_summary,
        baseline=baseline,
        max_allowed_drop_pct=args.max_drop_pct,
    )

    # 6. Save JSON Output Summary
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(current_summary.to_dict(), f, indent=2)
    print(f"[EVAL-CI] Evaluation results saved to: {output_path.resolve()}")

    # 7. Generate & Save Markdown Report
    md_content = RegressionDetector.format_markdown_report(
        current=current_summary,
        baseline=baseline,
        report=report,
    )
    if args.markdown_report:
        md_path = Path(args.markdown_report)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"[EVAL-CI] Markdown summary saved to: {md_path.resolve()}")

    # Print Summary Table to stdout
    print("\n" + "=" * 80)
    print(md_content)
    print("=" * 80 + "\n")

    # 8. Regression Gate Evaluation
    if report.has_regression:
        print(f"[EVAL-CI] ❌ REGRESSION DETECTED: {len(report.breaches)} quality breach(es) found:")
        for b in report.breaches:
            print(f"  - [{b.severity}] {b.metric_name}: Actual {b.actual_value} vs Threshold {b.threshold_value} ({b.comparator})")
            print(f"    Details: {b.description}")

        if args.fail_on_regression:
            print("\n[EVAL-CI] 🚫 CI BUILD FAILED: Model or prompt changes caused quality to drop beyond acceptable boundaries.")
            return 1
        else:
            print("\n[EVAL-CI] ⚠️ Quality dropped but --no-fail-on-regression was specified. Build continuing.")
            return 0
    else:
        print("[EVAL-CI] ✅ ALL QUALITY CHECKS PASSED: Model and prompts adhere strictly to institutional standards.")
        return 0


def main():
    exit_code = asyncio.run(run_cli())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
