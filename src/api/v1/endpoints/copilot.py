
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....application.dtos import (
    ChatRequest,
    ChatResponse,
    ConversationCreateDto,
    ConversationResponseDto,
)
from ....application.services.conversation_service import ConversationService
from ....infrastructure.database import get_db_session
from ....security.context import RequestSecurityContext
from ....security.guards import require_permissions

router = APIRouter(prefix="/copilot", tags=["Financial Copilot"])


@router.post("/chat", response_model=ChatResponse, summary="Conversational Financial Copilot")
async def copilot_chat(
    request: ChatRequest,
    context: RequestSecurityContext = Depends(require_permissions("conversations:write")),
):
    """
    Primary endpoint for financial research and risk reasoning queries.
    (Full multi-agent orchestration wired in Phase 4).
    """
    return ChatResponse(
        thread_id=request.thread_id or "thread-preview-001",
        query=request.query,
        response=f"Financial Copilot acknowledged query for tenant '{context.tenant_id}': {request.query[:100]}...",
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

