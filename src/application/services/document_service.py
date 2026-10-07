from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import (
    Document,
    DocumentMetadata,
    DocumentType,
    DocumentVersion,
)
from ...infrastructure.repositories.document_repository import DocumentRepository
from ...infrastructure.repositories.pagination import PagedResult, PageParams
from ...security.context import RequestSecurityContext
from ...security.rbac import enforce_permission, enforce_tenant_isolation


class DocumentService:
    """Service layer for financial documents enforcing RBAC, tenant boundaries, and concurrency."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DocumentRepository(session)

    async def get_document(self, context: RequestSecurityContext, document_id: str) -> Document:
        """Service layer retrieval with RBAC and tenant validation."""
        enforce_permission(context, "documents:read")
        doc = await self.repo.get_by_id(tenant_id=context.tenant_id, document_id=document_id)
        enforce_tenant_isolation(context, doc.tenant_id)
        return doc

    async def list_documents(
        self,
        context: RequestSecurityContext,
        ticker: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        """Lists documents strictly bounded to context.tenant_id."""
        enforce_permission(context, "documents:read")
        return await self.repo.list_by_tenant(
            tenant_id=context.tenant_id,
            ticker=ticker,
            limit=limit,
            offset=offset,
        )

    async def list_paginated(
        self,
        context: RequestSecurityContext,
        page_params: PageParams,
        ticker: str | None = None,
        doc_type: DocumentType | None = None,
    ) -> PagedResult[Document]:
        """Returns paginated document catalog."""
        enforce_permission(context, "documents:read")
        return await self.repo.list_paginated(
            tenant_id=context.tenant_id,
            page_params=page_params,
            ticker=ticker,
            doc_type=doc_type,
        )

    async def create_document(
        self,
        context: RequestSecurityContext,
        title: str,
        ticker: str | None,
        doc_type: DocumentType,
        content: str | None = None,
        content_hash: str = "hash-default",
        s3_raw_uri: str = "s3://default/path",
        file_size_bytes: int = 0,
        company_name: str | None = None,
    ) -> Document:
        """Creates document verifying documents:write permission."""
        enforce_permission(context, "documents:write")
        return await self.repo.create(
            tenant_id=context.tenant_id,
            title=title,
            ticker=ticker,
            company_name=company_name,
            doc_type=doc_type,
            fiscal_year=2024,
            fiscal_period="FY",
            content=content,
            content_hash=content_hash,
            s3_raw_uri=s3_raw_uri,
            file_size_bytes=file_size_bytes,
        )

    async def add_version(
        self,
        context: RequestSecurityContext,
        document_id: str,
        s3_uri: str,
        content_hash: str,
        file_size_bytes: int = 0,
        chunk_count: int = 0,
        change_summary: str | None = None,
    ) -> DocumentVersion:
        """Adds a version snapshot to a document."""
        enforce_permission(context, "documents:write")
        return await self.repo.add_version(
            tenant_id=context.tenant_id,
            document_id=document_id,
            s3_uri=s3_uri,
            content_hash=content_hash,
            file_size_bytes=file_size_bytes,
            chunk_count=chunk_count,
            change_summary=change_summary,
        )

    async def add_metadata(
        self,
        context: RequestSecurityContext,
        document_id: str,
        meta_key: str,
        meta_value: str,
        data_type: str = "string",
    ) -> DocumentMetadata:
        """Attaches key-value metadata to a document."""
        enforce_permission(context, "documents:write")
        return await self.repo.add_metadata(
            tenant_id=context.tenant_id,
            document_id=document_id,
            meta_key=meta_key,
            meta_value=meta_value,
            data_type=data_type,
        )

    async def update_document(
        self,
        context: RequestSecurityContext,
        document_id: str,
        expected_version: int,
        title: str | None = None,
        content: str | None = None,
    ) -> Document:
        """Updates document enforcing optimistic concurrency."""
        enforce_permission(context, "documents:write")
        return await self.repo.update_with_optimistic_lock(
            tenant_id=context.tenant_id,
            document_id=document_id,
            expected_version=expected_version,
            title=title,
            content=content,
        )

    async def delete_document(self, context: RequestSecurityContext, document_id: str) -> None:
        """Soft-deletes a document."""
        enforce_permission(context, "documents:delete")
        await self.repo.soft_delete(tenant_id=context.tenant_id, document_id=document_id)
