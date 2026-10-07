import math
from collections.abc import Sequence
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class PageParams(BaseModel):
    """Pagination query parameters."""
    page: int = Field(default=1, ge=1, description="Page number, 1-indexed")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PagedResult(BaseModel, Generic[T]):
    """Standardized institutional pagination response envelope."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: Sequence[T]
    total_items: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool

    @classmethod
    def create(
        cls,
        items: Sequence[T],
        total_items: int,
        page_params: PageParams,
    ) -> "PagedResult[T]":
        total_pages = math.ceil(total_items / page_params.page_size) if total_items > 0 else 0
        return cls(
            items=items,
            total_items=total_items,
            page=page_params.page,
            page_size=page_params.page_size,
            total_pages=total_pages,
            has_next=page_params.page < total_pages,
            has_prev=page_params.page > 1,
        )


async def paginate_query(
    session: AsyncSession,
    statement: Select,
    page_params: PageParams,
) -> tuple[list, int]:
    """
    Executes paginated execution for a SQLAlchemy select statement.
    Returns: (items, total_count)
    """
    # 1. Total count query
    count_stmt = select(func.count()).select_from(statement.order_by(None).subquery())
    count_res = await session.execute(count_stmt)
    total_count = count_res.scalar_one() or 0

    # 2. Paginated items query
    paginated_stmt = statement.limit(page_params.limit).offset(page_params.offset)
    items_res = await session.execute(paginated_stmt)
    items = list(items_res.scalars().all())

    return items, total_count
