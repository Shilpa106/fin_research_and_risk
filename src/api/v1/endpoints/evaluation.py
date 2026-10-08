import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....evaluation.datasets import load_golden_evaluation_dataset
from ....evaluation.models import ThresholdConfig
from ....evaluation.regression import RegressionDetector
from ....evaluation.runner import EvaluationRunner
from ....infrastructure.database import get_db_session
from ....infrastructure.repositories.evaluation_repository import EvaluationRepository
from ....infrastructure.repositories.pagination import PageParams
from ....security.context import RequestSecurityContext
from ....security.guards import require_permissions

router = APIRouter(prefix="/evaluation", tags=["GenAI Evaluation Platform"])


class EvaluationRunRequest(BaseModel):
    domain: str | None = Field(default=None, description="Domain filter: research, risk, portfolio, safety")
    model_id: str = Field(default="claude-3-5-sonnet", description="Model identifier being evaluated")
    k: int = Field(default=5, ge=1, le=20, description="Top-K cutoff for retrieval metrics")


class EvaluationRunResponse(BaseModel):
    tenant_id: str
    dataset_name: str
    model_id: str
    summary: dict[str, Any]
    regression_report: dict[str, Any]
    passed: bool


class EvaluationItemDto(BaseModel):
    id: str
    tenant_id: str
    dataset_name: str
    model_id: str
    faithfulness_score: float
    answer_relevance_score: float
    hallucination_score: float
    total_eval_samples: int
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class EvaluationListResponse(BaseModel):
    items: list[EvaluationItemDto]
    total_items: int
    page: int
    page_size: int
    total_pages: int


@router.post("/run", response_model=EvaluationRunResponse, summary="Execute On-Demand GenAI Evaluation Benchmark")
async def run_evaluation(
    payload: EvaluationRunRequest,
    context: RequestSecurityContext = Depends(require_permissions("evaluation:run")),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Executes live empirical benchmark evaluation across RAG, Agent, and Safety pillars.
    Persists run telemetry into the Evaluation repository and evaluates against regression thresholds.
    """
    dataset = load_golden_evaluation_dataset(domain=payload.domain)
    runner = EvaluationRunner(session=session)
    summary = await runner.run_evaluation_suite(
        dataset=dataset,
        model_id=payload.model_id,
        k=payload.k,
        tenant_id=context.tenant_id,
    )

    # Evaluate against standard quality thresholds
    thresholds = ThresholdConfig()
    detector = RegressionDetector(thresholds=thresholds)
    regression_report = detector.check_regression(current=summary)

    return EvaluationRunResponse(
        tenant_id=context.tenant_id,
        dataset_name=summary.dataset_name,
        model_id=payload.model_id,
        summary=summary.to_dict(),
        regression_report=regression_report.to_dict(),
        passed=regression_report.passed,
    )


@router.get("/runs", response_model=EvaluationListResponse, summary="List Tenant Evaluation Benchmark Runs")
async def list_evaluation_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    dataset_name: str | None = Query(default=None),
    context: RequestSecurityContext = Depends(require_permissions("evaluation:read")),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Retrieves paginated evaluation benchmark runs strictly scoped to the requesting tenant.
    """
    repo = EvaluationRepository(session)
    page_params = PageParams(page=page, page_size=page_size)
    paged_result = await repo.list_paginated(
        tenant_id=context.tenant_id,
        page_params=page_params,
        dataset_name=dataset_name,
    )

    items = []
    for run in paged_result.items:
        meta = {}
        if run.metadata_json:
            try:
                meta = json.loads(run.metadata_json)
            except Exception:
                meta = {}
        items.append(
            EvaluationItemDto(
                id=run.id,
                tenant_id=run.tenant_id,
                dataset_name=run.dataset_name,
                model_id=run.model_id,
                faithfulness_score=run.faithfulness_score,
                answer_relevance_score=run.answer_relevance_score,
                hallucination_score=run.hallucination_score,
                total_eval_samples=run.total_eval_samples,
                status=run.status,
                metadata=meta,
                created_at=run.created_at.isoformat() if run.created_at else "",
            )
        )

    return EvaluationListResponse(
        items=items,
        total_items=paged_result.total_items,
        page=paged_result.page,
        page_size=paged_result.page_size,
        total_pages=paged_result.total_pages,
    )


@router.get("/runs/{run_id}", response_model=EvaluationItemDto, summary="Get Evaluation Run Details")
async def get_evaluation_run(
    run_id: str,
    context: RequestSecurityContext = Depends(require_permissions("evaluation:read")),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Retrieves full details of a specific evaluation run with tenant isolation enforcement.
    """
    repo = EvaluationRepository(session)
    run = await repo.get_by_id(tenant_id=context.tenant_id, eval_id=run_id)

    meta = {}
    if run.metadata_json:
        try:
            meta = json.loads(run.metadata_json)
        except Exception:
            meta = {}

    return EvaluationItemDto(
        id=run.id,
        tenant_id=run.tenant_id,
        dataset_name=run.dataset_name,
        model_id=run.model_id,
        faithfulness_score=run.faithfulness_score,
        answer_relevance_score=run.answer_relevance_score,
        hallucination_score=run.hallucination_score,
        total_eval_samples=run.total_eval_samples,
        status=run.status,
        metadata=meta,
        created_at=run.created_at.isoformat() if run.created_at else "",
    )
