
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....application.dtos import (
    ChatRequest,
    ChatResponse,
    ConversationCreateDto,
    ConversationResponseDto,
)
from ....application.services.conversation_service import ConversationService
from ....domain.exceptions import GuardrailViolationException
from ....infrastructure.database import get_db_session
from ....security.context import RequestSecurityContext
from ....security.guardrails import GenAISecurityManager
from ....security.guards import require_permissions

security_manager = GenAISecurityManager()
router = APIRouter(prefix="/copilot", tags=["Financial Copilot"])


@router.post("/chat", response_model=ChatResponse, summary="Conversational Financial Copilot")
async def copilot_chat(
    request: ChatRequest,
    context: RequestSecurityContext = Depends(require_permissions("conversations:write")),
):
    """
    Primary endpoint for financial research and risk reasoning queries with layered GenAI security.
    """
    # 1. Input Guardrail Verification
    input_eval = security_manager.evaluate_input(prompt=request.query, user_id=context.user_id)
    if not input_eval.is_safe:
        violations_summary = [f"{v.violation_type.value}: {v.message}" for v in input_eval.violations]
        raise GuardrailViolationException(
            message=f"Input rejected by GenAI security guardrails: {'; '.join(violations_summary)}",
            violations=[v.model_dump(mode="json") for v in input_eval.violations],
        )

    # 2. Output Generation & Output Guardrail Verification
    raw_response = (
        f"Financial Copilot acknowledged query for tenant '{context.tenant_id}': "
        f"{input_eval.sanitized_prompt[:100]}..."
    )
    output_eval = security_manager.evaluate_output(output_text=raw_response)

    return ChatResponse(
        thread_id=request.thread_id or "thread-preview-001",
        query=request.query,
        response=output_eval.sanitized_output,
        citations=[],
        requires_hitl=False,
        cached=False,
    )


@router.post("/conversations", response_model=ConversationResponseDto, summary="Create Conversation Session")
async def create_conversation(
    payload: ConversationCreateDto,
    context: RequestSecurityContext = Depends(require_permissions("conversations:write")),
    session: AsyncSession = Depends(get_db_session),
):
    """Creates conversation thread scoped to authenticated user and tenant."""
    service = ConversationService(session)
    thread = await service.create_conversation(context=context, title=payload.title)
    return ConversationResponseDto(
        id=thread.id,
        tenant_id=thread.tenant_id,
        user_id=thread.user_id,
        title=thread.title,
        is_archived=thread.is_archived,
    )


@router.get("/conversations/{thread_id}", response_model=ConversationResponseDto, summary="Get Conversation Session")
async def get_conversation(
    thread_id: str,
    context: RequestSecurityContext = Depends(require_permissions("conversations:read")),
    session: AsyncSession = Depends(get_db_session),
):
    """Retrieves conversation thread enforcing tenant isolation and permissions."""
    service = ConversationService(session)
    thread = await service.get_conversation(context=context, thread_id=thread_id)
    return ConversationResponseDto(
        id=thread.id,
        tenant_id=thread.tenant_id,
        user_id=thread.user_id,
        title=thread.title,
        is_archived=thread.is_archived,
    )


@router.get("/conversations", response_model=list[ConversationResponseDto], summary="List Tenant Conversations")
async def list_conversations(
    context: RequestSecurityContext = Depends(require_permissions("conversations:read")),
    session: AsyncSession = Depends(get_db_session),
):
    """Lists conversation sessions strictly bounded to caller tenant."""
    service = ConversationService(session)
    threads = await service.list_conversations(context=context)
    return [
        ConversationResponseDto(
            id=t.id,
            tenant_id=t.tenant_id,
            user_id=t.user_id,
            title=t.title,
            is_archived=t.is_archived,
        )
        for t in threads
    ]

