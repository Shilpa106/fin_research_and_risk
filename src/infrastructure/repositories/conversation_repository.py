from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...domain.entities import Conversation, Message
from ...domain.exceptions import (
    EntityNotFoundException,
    OptimisticConcurrencyException,
    TenantIsolationViolationException,
)
from .pagination import PagedResult, PageParams, paginate_query


class ConversationRepository:
    """
    Tenant-isolated repository for agent conversation sessions and messages.
    Guarantees no cross-tenant query execution, supports pagination and optimistic concurrency.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(
        self,
        tenant_id: str,
        thread_id: str,
        include_deleted: bool = False,
        load_messages: bool = True,
    ) -> Conversation:
        """Retrieves conversation thread strictly verifying tenant ownership."""
        stmt = select(Conversation).where(Conversation.id == thread_id)
        if not include_deleted:
            stmt = stmt.where(Conversation.is_deleted == False)  # noqa: E712
        if load_messages:
            stmt = stmt.options(selectinload(Conversation.messages))

        result = await self.session.execute(stmt)
        thread = result.scalar_one_or_none()

        if not thread:
            raise EntityNotFoundException("Conversation", thread_id)

        # REPOSITORY-LAYER TENANT ISOLATION CHECK
        if thread.tenant_id != tenant_id:
            raise TenantIsolationViolationException(
                f"Conversation thread '{thread_id}' belongs to tenant '{thread.tenant_id}', but was accessed by tenant '{tenant_id}'."
            )

        if load_messages:
            await self.session.refresh(thread, ["messages"])

        return thread

    async def list_by_tenant(
        self,
        tenant_id: str,
        user_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[Conversation]:
        """Lists active conversation threads strictly for the authenticated tenant."""
        stmt = select(Conversation).where(Conversation.tenant_id == tenant_id)
        if not include_deleted:
            stmt = stmt.where(Conversation.is_deleted == False)  # noqa: E712
        if user_id:
            stmt = stmt.where(Conversation.user_id == user_id)

        stmt = stmt.order_by(Conversation.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_paginated(
        self,
        tenant_id: str,
        page_params: PageParams,
        user_id: str | None = None,
        include_deleted: bool = False,
    ) -> PagedResult[Conversation]:
        """Returns paginated conversations list."""
        stmt = select(Conversation).where(Conversation.tenant_id == tenant_id)
        if not include_deleted:
            stmt = stmt.where(Conversation.is_deleted == False)  # noqa: E712
        if user_id:
            stmt = stmt.where(Conversation.user_id == user_id)

        stmt = stmt.order_by(Conversation.created_at.desc())
        items, total_count = await paginate_query(self.session, stmt, page_params)
        return PagedResult.create(items=items, total_items=total_count, page_params=page_params)

    async def create(self, tenant_id: str, user_id: str, title: str) -> Conversation:
        """Creates new conversation thread scoped to tenant."""
        thread = Conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
            is_archived=False,
            version=1,
            is_deleted=False,
        )
        self.session.add(thread)
        await self.session.commit()
        await self.session.refresh(thread)
        return thread

    async def add_message(
        self,
        tenant_id: str,
        conversation_id: str,
        role: str,
        content: str,
        token_count: int = 0,
        citations_json: str = "[]",
        model_name: str | None = None,
        latency_ms: float | None = None,
    ) -> Message:
        """Appends a new turn message to the conversation."""
        await self.get_by_id(tenant_id=tenant_id, thread_id=conversation_id)
        msg = Message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            token_count=token_count,
            citations_json=citations_json,
            model_name=model_name,
            latency_ms=latency_ms,
            is_deleted=False,
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    async def list_messages(
        self,
        tenant_id: str,
        conversation_id: str,
        limit: int = 100,
    ) -> list[Message]:
        """Lists chronological messages for a conversation within tenant boundary."""
        await self.get_by_id(tenant_id=tenant_id, thread_id=conversation_id)
        stmt = (
            select(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation_id,
                Message.is_deleted == False,  # noqa: E712
            )
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def update_with_optimistic_lock(
        self,
        tenant_id: str,
        thread_id: str,
        expected_version: int,
        title: str | None = None,
        is_archived: bool | None = None,
    ) -> Conversation:
        """Updates conversation title or archive state with optimistic concurrency check."""
        await self.get_by_id(tenant_id=tenant_id, thread_id=thread_id)

        update_values: dict = {
            "version": Conversation.version + 1,
            "updated_at": datetime.utcnow(),
        }
        if title is not None:
            update_values["title"] = title
        if is_archived is not None:
            update_values["is_archived"] = is_archived

        stmt = (
            update(Conversation)
            .where(
                Conversation.id == thread_id,
                Conversation.tenant_id == tenant_id,
                Conversation.version == expected_version,
                Conversation.is_deleted == False,  # noqa: E712
            )
            .values(**update_values)
        )
        res = await self.session.execute(stmt)
        await self.session.commit()

        if getattr(res, "rowcount", 0) == 0:
            raise OptimisticConcurrencyException(
                entity_name="Conversation",
                entity_id=thread_id,
                expected_version=expected_version,
            )

        return await self.get_by_id(tenant_id=tenant_id, thread_id=thread_id)

    async def soft_delete(self, tenant_id: str, thread_id: str) -> None:
        """Soft-deletes a conversation thread."""
        thread = await self.get_by_id(tenant_id=tenant_id, thread_id=thread_id)
        thread.is_deleted = True
        thread.deleted_at = datetime.utcnow()
        await self.session.commit()
