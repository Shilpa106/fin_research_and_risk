from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Conversation, Message
from ...infrastructure.repositories.conversation_repository import ConversationRepository
from ...infrastructure.repositories.pagination import PagedResult, PageParams
from ...security.context import RequestSecurityContext
from ...security.rbac import enforce_permission, enforce_tenant_isolation


class ConversationService:
    """Service layer for conversational agent sessions, messages, and optimistic concurrency."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ConversationRepository(session)

    async def get_conversation(self, context: RequestSecurityContext, thread_id: str) -> Conversation:
        """Retrieves conversation thread strictly verifying permissions and tenant."""
        enforce_permission(context, "conversations:read")
        thread = await self.repo.get_by_id(tenant_id=context.tenant_id, thread_id=thread_id)
        enforce_tenant_isolation(context, thread.tenant_id)
        return thread

    async def list_conversations(
        self,
        context: RequestSecurityContext,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        """Lists conversations for authenticated tenant."""
        enforce_permission(context, "conversations:read")
        return await self.repo.list_by_tenant(tenant_id=context.tenant_id, limit=limit, offset=offset)

    async def list_paginated(
        self,
        context: RequestSecurityContext,
        page_params: PageParams,
        user_id: str | None = None,
    ) -> PagedResult[Conversation]:
        """Returns paginated conversations list."""
        enforce_permission(context, "conversations:read")
        return await self.repo.list_paginated(
            tenant_id=context.tenant_id,
            page_params=page_params,
            user_id=user_id,
        )

    async def create_conversation(self, context: RequestSecurityContext, title: str) -> Conversation:
        """Creates new conversation thread."""
        enforce_permission(context, "conversations:write")
        return await self.repo.create(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            title=title,
        )

    async def add_message(
        self,
        context: RequestSecurityContext,
        conversation_id: str,
        role: str,
        content: str,
        token_count: int = 0,
        citations_json: str = "[]",
        model_name: str | None = None,
        latency_ms: float | None = None,
    ) -> Message:
        """Appends dialogue message turn to a conversation."""
        enforce_permission(context, "conversations:write")
        return await self.repo.add_message(
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            token_count=token_count,
            citations_json=citations_json,
            model_name=model_name,
            latency_ms=latency_ms,
        )

    async def list_messages(
        self,
        context: RequestSecurityContext,
        conversation_id: str,
        limit: int = 100,
    ) -> list[Message]:
        """Lists messages for a conversation session."""
        enforce_permission(context, "conversations:read")
        return await self.repo.list_messages(
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            limit=limit,
        )

    async def update_conversation(
        self,
        context: RequestSecurityContext,
        conversation_id: str,
        expected_version: int,
        title: str | None = None,
        is_archived: bool | None = None,
    ) -> Conversation:
        """Updates conversation title or archive status with optimistic concurrency control."""
        enforce_permission(context, "conversations:write")
        return await self.repo.update_with_optimistic_lock(
            tenant_id=context.tenant_id,
            thread_id=conversation_id,
            expected_version=expected_version,
            title=title,
            is_archived=is_archived,
        )

    async def delete_conversation(self, context: RequestSecurityContext, conversation_id: str) -> None:
        """Soft-deletes a conversation."""
        enforce_permission(context, "conversations:write")
        await self.repo.soft_delete(tenant_id=context.tenant_id, thread_id=conversation_id)
