from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...domain.entities import AgentRun, ToolExecution
from ...domain.exceptions import EntityNotFoundException, TenantIsolationViolationException
from .pagination import PagedResult, PageParams, paginate_query


class AgentRunRepository:
    """
    Tenant-isolated repository for tracking multi-agent reasoning runs and tool calls.
    Provides execution history, tool metrics, and paginated audit reporting.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_agent_run(
        self,
        tenant_id: str,
        agent_name: str,
        input_prompt: str,
        user_id: str | None = None,
        conversation_id: str | None = None,
    ) -> AgentRun:
        """Initializes a tracked agent run."""
        run = AgentRun(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            agent_name=agent_name,
            input_prompt=input_prompt,
            status="RUNNING",
            total_tokens=0,
            cost_usd=0.0,
            latency_ms=0.0,
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def update_agent_run(
        self,
        tenant_id: str,
        run_id: str,
        status: str,
        output_summary: str | None = None,
        total_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
        error_message: str | None = None,
        load_tools: bool = True,
    ) -> AgentRun:
        """Updates agent run completion metrics."""
        run = await self.get_by_id(tenant_id=tenant_id, run_id=run_id, load_tools=load_tools)
        run.status = status
        run.output_summary = output_summary
        run.total_tokens = total_tokens
        run.cost_usd = cost_usd
        run.latency_ms = latency_ms
        run.error_message = error_message
        run.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(run)
        if load_tools:
            await self.session.refresh(run, ["tool_executions"])
        return run

    async def record_tool_execution(
        self,
        tenant_id: str,
        agent_run_id: str,
        tool_name: str,
        input_parameters_json: str = "{}",
        output_result_json: str = "{}",
        status: str = "SUCCESS",
        duration_ms: float = 0.0,
    ) -> ToolExecution:
        """Records a completed or failed tool invocation."""
        await self.get_by_id(tenant_id=tenant_id, run_id=agent_run_id, load_tools=False)

        tool_exec = ToolExecution(
            tenant_id=tenant_id,
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            input_parameters_json=input_parameters_json,
            output_result_json=output_result_json,
            status=status,
            duration_ms=duration_ms,
        )
        self.session.add(tool_exec)
        await self.session.commit()
        await self.session.refresh(tool_exec)
        return tool_exec

    async def get_by_id(
        self,
        tenant_id: str,
        run_id: str,
        load_tools: bool = True,
    ) -> AgentRun:
        """Retrieves an agent run with tenant isolation assertion."""
        stmt = select(AgentRun).where(AgentRun.id == run_id)
        if load_tools:
            stmt = stmt.options(selectinload(AgentRun.tool_executions))

        res = await self.session.execute(stmt)
        run = res.scalar_one_or_none()

        if not run:
            raise EntityNotFoundException("AgentRun", run_id)

        if run.tenant_id != tenant_id:
            raise TenantIsolationViolationException(
                f"AgentRun '{run_id}' belongs to tenant '{run.tenant_id}', but was requested by tenant '{tenant_id}'."
            )

        if load_tools:
            await self.session.refresh(run, ["tool_executions"])

        return run

    async def list_paginated(
        self,
        tenant_id: str,
        page_params: PageParams,
        agent_name: str | None = None,
        status: str | None = None,
    ) -> PagedResult[AgentRun]:
        """Returns paginated agent run history."""
        stmt = select(AgentRun).where(AgentRun.tenant_id == tenant_id)
        if agent_name:
            stmt = stmt.where(AgentRun.agent_name == agent_name)
        if status:
            stmt = stmt.where(AgentRun.status == status)

        stmt = stmt.order_by(AgentRun.created_at.desc())
        items, total_count = await paginate_query(self.session, stmt, page_params)
        return PagedResult.create(items=items, total_items=total_count, page_params=page_params)
