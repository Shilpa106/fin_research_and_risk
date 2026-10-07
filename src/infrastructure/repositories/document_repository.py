from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...domain.entities import (
    Document,
    DocumentMetadata,
    DocumentType,
    DocumentVersion,
    IngestionStatus,
)
from ...domain.exceptions import (
    EntityNotFoundException,
    OptimisticConcurrencyException,
    TenantIsolationViolationException,
)
from .pagination import PagedResult, PageParams, paginate_query


class DocumentRepository:
    """
    Tenant-isolated repository for Document entities.
    Guarantees no cross-tenant query execution at the database abstraction level.
    Supports versions, metadata, soft deletion, optimistic concurrency, and pagination.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(
        self,
        tenant_id: str,
        document_id: str,
        include_deleted: bool = False,
        load_relations: bool = True,
    ) -> Document:
        """Retrieves a document strictly verifying tenant boundary."""
        stmt = select(Document).where(Document.id == document_id)
        if not include_deleted:
            stmt = stmt.where(Document.is_deleted == False)  # noqa: E712
        if load_relations:
            stmt = stmt.options(
                selectinload(Document.versions),
                selectinload(Document.metadata_items),
            )

        result = await self.session.execute(stmt)
        doc = result.scalar_one_or_none()

        if not doc:
            raise EntityNotFoundException("Document", document_id)

        # REPOSITORY-LAYER TENANT ISOLATION CHECK
        if doc.tenant_id != tenant_id:
            raise TenantIsolationViolationException(
                f"Repository isolation breach: Document '{document_id}' belongs to tenant '{doc.tenant_id}', but was requested by tenant '{tenant_id}'."
            )

        if load_relations:
            await self.session.refresh(doc, ["versions", "metadata_items"])

        return doc

    async def list_by_tenant(
        self,
        tenant_id: str,
        ticker: str | None = None,
        doc_type: DocumentType | None = None,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[Document]:
        """Lists documents strictly scoped to tenant_id."""
        stmt = select(Document).where(Document.tenant_id == tenant_id)
        if not include_deleted:
            stmt = stmt.where(Document.is_deleted == False)  # noqa: E712
        if ticker:
            stmt = stmt.where(Document.ticker == ticker)
        if doc_type:
            stmt = stmt.where(Document.doc_type == doc_type)

        stmt = stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_paginated(
        self,
        tenant_id: str,
        page_params: PageParams,
        ticker: str | None = None,
        doc_type: DocumentType | None = None,
        include_deleted: bool = False,
    ) -> PagedResult[Document]:
        """Returns paginated document list with metadata envelope."""
        stmt = select(Document).where(Document.tenant_id == tenant_id)
        if not include_deleted:
            stmt = stmt.where(Document.is_deleted == False)  # noqa: E712
        if ticker:
            stmt = stmt.where(Document.ticker == ticker)
        if doc_type:
            stmt = stmt.where(Document.doc_type == doc_type)

        stmt = stmt.order_by(Document.created_at.desc())
        items, total_count = await paginate_query(self.session, stmt, page_params)
        return PagedResult.create(items=items, total_items=total_count, page_params=page_params)

    async def create(
        self,
        tenant_id: str,
        title: str,
        ticker: str | None,
        doc_type: DocumentType,
        fiscal_year: int | None = 2024,
        fiscal_period: str | None = "FY",
        content: str | None = None,
        content_hash: str = "hash-default",
        s3_raw_uri: str = "s3://default/path",
        file_size_bytes: int = 0,
        company_name: str | None = None,
    ) -> Document:
        """Persists a new document with mandatory tenant_id attribution and initial version."""
        doc = Document(
            tenant_id=tenant_id,
            title=title,
            ticker=ticker,
            company_name=company_name,
            doc_type=doc_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            content=content,
            content_hash=content_hash,
            s3_raw_uri=s3_raw_uri,
            file_size_bytes=file_size_bytes,
            status=IngestionStatus.INDEXED,
            version=1,
            is_deleted=False,
        )
        self.session.add(doc)
        await self.session.flush()

        # Create initial DocumentVersion
        initial_version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=doc.id,
            version_number=1,
            s3_uri=s3_raw_uri,
            content_hash=content_hash,
            file_size_bytes=file_size_bytes,
            chunk_count=doc.chunk_count,
            status=IngestionStatus.INDEXED,
            change_summary="Initial document ingestion",
        )
        self.session.add(initial_version)
        doc.current_version_id = initial_version.id
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def add_version(
        self,
        tenant_id: str,
        document_id: str,
        s3_uri: str,
        content_hash: str,
        file_size_bytes: int = 0,
        chunk_count: int = 0,
        change_summary: str | None = None,
    ) -> DocumentVersion:
        """Appends a new version snapshot to an existing document."""
        doc = await self.get_by_id(tenant_id=tenant_id, document_id=document_id, load_relations=True)
        new_version_num = len(doc.versions) + 1 if doc.versions else 2

        version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document_id,
            version_number=new_version_num,
            s3_uri=s3_uri,
            content_hash=content_hash,
            file_size_bytes=file_size_bytes,
            chunk_count=chunk_count,
            status=IngestionStatus.INDEXED,
            change_summary=change_summary,
        )
        self.session.add(version)
        doc.current_version_id = version.id
        doc.content_hash = content_hash
        doc.s3_raw_uri = s3_uri
        doc.version += 1
        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def add_metadata(
        self,
        tenant_id: str,
        document_id: str,
        meta_key: str,
        meta_value: str,
        data_type: str = "string",
    ) -> DocumentMetadata:
        """Attaches structured metadata to a document."""
        await self.get_by_id(tenant_id=tenant_id, document_id=document_id, load_relations=False)
        meta = DocumentMetadata(
            tenant_id=tenant_id,
            document_id=document_id,
            meta_key=meta_key,
            meta_value=meta_value,
            data_type=data_type,
        )
        self.session.add(meta)
        await self.session.commit()
        await self.session.refresh(meta)
        return meta

    async def update_with_optimistic_lock(
        self,
        tenant_id: str,
        document_id: str,
        expected_version: int,
        title: str | None = None,
        content: str | None = None,
    ) -> Document:
        """
        Updates document attributes enforcing optimistic concurrency control.
        Raises OptimisticConcurrencyException if another transaction bumped the version.
        """
        # Ensure document exists and belongs to tenant
        await self.get_by_id(tenant_id=tenant_id, document_id=document_id)

        update_values: dict = {
            "version": Document.version + 1,
            "updated_at": datetime.utcnow(),
        }
        if title is not None:
            update_values["title"] = title
        if content is not None:
            update_values["content"] = content

        stmt = (
            update(Document)
            .where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.version == expected_version,
                Document.is_deleted == False,  # noqa: E712
            )
            .values(**update_values)
        )
        res = await self.session.execute(stmt)
        await self.session.commit()

        if getattr(res, "rowcount", 0) == 0:
            raise OptimisticConcurrencyException(
                entity_name="Document",
                entity_id=document_id,
                expected_version=expected_version,
            )

        return await self.get_by_id(tenant_id=tenant_id, document_id=document_id)

    async def soft_delete(self, tenant_id: str, document_id: str) -> None:
        """Soft-deletes a document for SEC 17a-4 compliance."""
        doc = await self.get_by_id(tenant_id=tenant_id, document_id=document_id)
        doc.is_deleted = True
        doc.deleted_at = datetime.utcnow()
        await self.session.commit()
