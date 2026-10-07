from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...domain.entities import TenantMembership, User
from ...domain.exceptions import EntityNotFoundException
from .pagination import PagedResult, PageParams, paginate_query


class UserRepository:
    """Repository for managing platform Users."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: str, include_deleted: bool = False, load_memberships: bool = True) -> User:
        stmt = select(User).where(User.id == user_id)
        if not include_deleted:
            stmt = stmt.where(User.is_deleted == False)  # noqa: E712
        if load_memberships:
            stmt = stmt.options(selectinload(User.memberships).selectinload(TenantMembership.roles))
        res = await self.session.execute(stmt)
        user = res.scalar_one_or_none()
        if not user:
            raise EntityNotFoundException("User", user_id)
        return user

    async def get_by_email(self, email: str, include_deleted: bool = False) -> User | None:
        stmt = (
            select(User)
            .options(selectinload(User.memberships).selectinload(TenantMembership.roles))
            .where(User.email == email)
        )
        if not include_deleted:
            stmt = stmt.where(User.is_deleted == False)  # noqa: E712
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create(
        self,
        email: str,
        hashed_password: str,
        full_name: str | None = None,
        is_superuser: bool = False,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            is_active=True,
            is_superuser=is_superuser,
            is_deleted=False,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def list_paginated(self, page_params: PageParams, include_deleted: bool = False) -> PagedResult[User]:
        stmt = select(User)
        if not include_deleted:
            stmt = stmt.where(User.is_deleted == False)  # noqa: E712
        stmt = stmt.order_by(User.created_at.desc())
        items, total_count = await paginate_query(self.session, stmt, page_params)
        return PagedResult.create(items=items, total_items=total_count, page_params=page_params)

    async def soft_delete(self, user_id: str) -> None:
        user = await self.get_by_id(user_id, load_memberships=False)
        user.is_deleted = True
        user.deleted_at = datetime.utcnow()
        await self.session.commit()
