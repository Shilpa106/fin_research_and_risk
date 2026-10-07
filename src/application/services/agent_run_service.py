from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import AgentRun, ToolExecution
from ...infrastructure.repositories.agent_run_repository import AgentRunRepository
from ...infrastructure.repositories.pagination import PagedResult, PageParams
from ...security.context import RequestSecurityContext
from ...security.rbac import enforce_permission, enforce_tenant_isolation


class AgentRunService:
    """Service layer for multi-agent reasoning execution tracking."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = AgentRunRepository(session)

    async def start_run(
        self,
        context: RequestSecurityContext,
        agent_name: str,
        input_prompt: str,
        conversation_id: str | None = None,
    ) -> AgentRun:
        """Starts a tracked agent workflow run."""
        enforce_permission(context, "conversations:write")
        return await self.repo.create_agent_run(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            conversation_id=conversation_id,
            agent_name=agent_name,
            input_prompt=input_prompt,
        )

    async def complete_run(
        self,
        context: RequestSecurityContext,
        run_id: str,
        status: str,
        output_summary: str | None = None,
        total_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
        error_message: str | None = None,
    ) -> AgentRun:
        """Finalizes an agent run."""
        enforce_permission(context, "conversations:write")
        return await self.repo.update_agent_run(
            tenant_id=context.tenant_id,
            run_id=run_id,
            status=status,
            output_summary=output_summary,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            error_message=error_message,
        )

    async def record_tool_call(
        self,
        context: RequestSecurityContext,
        agent_run_id: str,
        tool_name: str,
        input_parameters_json: str = "{}",
        output_result_json: str = "{}",
        status: str = "SUCCESS",
        duration_ms: float = 0.0,
    ) -> ToolExecution:
        """Records a tool invocation executed during an agent run."""
        enforce_permission(context, "conversations:write")
        return await self.repo.record_tool_execution(
            tenant_id=context.tenant_id,
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            input_parameters_json=input_parameters_json,
            output_result_json=output_result_json,
            status=status,
            duration_ms=duration_ms,
        )

    async def get_run(self, context: RequestSecurityContext, run_id: str) -> AgentRun:
        """Retrieves an agent run with tool calls."""
        enforce_permission(context, "conversations:read")
        run = await self.repo.get_by_id(tenant_id=context.tenant_id, run_id=run_id)
        enforce_tenant_isolation(context, run.tenant_id)
        return run

    async def list_runs(
        self,
        context: RequestSecurityContext,
        page_params: PageParams,
        agent_name: str | None = None,
        status: str | None = None,
    ) -> PagedResult[AgentRun]:
        """Lists paginated agent runs for tenant."""
        enforce_permission(context, "conversations:read")
        return await self.repo.list_paginated(
            tenant_id=context.tenant_id,
            page_params=page_params,
            agent_name=agent_name,
            status=status,
        )
