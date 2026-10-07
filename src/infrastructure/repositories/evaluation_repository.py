from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import EvaluationRun
from ...domain.exceptions import EntityNotFoundException, TenantIsolationViolationException
from .pagination import PagedResult, PageParams, paginate_query


class EvaluationRepository:
    """
    Tenant-isolated repository for AI evaluation benchmark runs and guardrail metrics.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_evaluation_run(
        self,
        tenant_id: str,
        dataset_name: str,
        model_id: str,
        faithfulness_score: float = 0.0,
        answer_relevance_score: float = 0.0,
        hallucination_score: float = 0.0,
        total_eval_samples: int = 0,
        status: str = "COMPLETED",
        metadata_json: str = "{}",
    ) -> EvaluationRun:
        """Stores a completed evaluation benchmark run."""
        run = EvaluationRun(
            tenant_id=tenant_id,
            dataset_name=dataset_name,
            model_id=model_id,
            faithfulness_score=faithfulness_score,
            answer_relevance_score=answer_relevance_score,
            hallucination_score=hallucination_score,
            total_eval_samples=total_eval_samples,
            status=status,
            metadata_json=metadata_json,
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def get_by_id(self, tenant_id: str, eval_id: str) -> EvaluationRun:
        """Retrieves an evaluation run strictly checking tenant ownership."""
        stmt = select(EvaluationRun).where(EvaluationRun.id == eval_id)
        res = await self.session.execute(stmt)
        run = res.scalar_one_or_none()

        if not run:
            raise EntityNotFoundException("EvaluationRun", eval_id)

        if run.tenant_id != tenant_id:
            raise TenantIsolationViolationException(
                f"EvaluationRun '{eval_id}' belongs to tenant '{run.tenant_id}', but was requested by tenant '{tenant_id}'."
            )

        return run

    async def list_paginated(
        self,
        tenant_id: str,
        page_params: PageParams,
        dataset_name: str | None = None,
    ) -> PagedResult[EvaluationRun]:
        """Returns paginated evaluation runs."""
        stmt = select(EvaluationRun).where(EvaluationRun.tenant_id == tenant_id)
        if dataset_name:
            stmt = stmt.where(EvaluationRun.dataset_name == dataset_name)

        stmt = stmt.order_by(EvaluationRun.created_at.desc())
        items, total_count = await paginate_query(self.session, stmt, page_params)
        return PagedResult.create(items=items, total_items=total_count, page_params=page_params)
