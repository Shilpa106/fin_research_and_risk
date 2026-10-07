import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Document, DocumentType, IngestionStatus
from ...events.document_events import DocumentUploadedEvent
from ...infrastructure.repositories.document_repository import DocumentRepository
from ...interfaces.queue import MessageQueue
from ...interfaces.storage import ObjectStorageService

logger = logging.getLogger(__name__)


@dataclass
class UploadResponse:
    """Descriptor returned to caller upon document upload initiation."""
    document_id: str
    tenant_id: str
    status: IngestionStatus
    s3_uri: str
    content_hash: str
    version_number: int
    is_duplicate: bool
    event_id: str


class IngestionService:
    """
    Application service managing the upload, deduplication, and ingestion dispatch
    for institutional financial research documents and regulatory filings.
    """

    QUEUE_NAME = "financial-document-ingestion"

    def __init__(
        self,
        storage: ObjectStorageService,
        queue: MessageQueue,
        session: AsyncSession,
    ):
        self.storage = storage
        self.queue = queue
        self.session = session
        self.doc_repo = DocumentRepository(session)

    async def ingest_document(
        self,
        tenant_id: str,
        file_name: str,
        data: bytes,
        mime_type: str = "application/pdf",
        title: str | None = None,
        doc_type: DocumentType = DocumentType.EQUITY_RESEARCH,
        ticker: str | None = None,
    ) -> UploadResponse:
        """
        Accepts raw file payload, computes checksum, enforces idempotency,
        stores in object storage, creates catalog record, and queues async ingestion event.
        """
        # 1. Compute SHA-256 Checksum
        content_hash = self.storage.compute_checksum(data)

        # 2. Idempotency Check: check if document with this content_hash already exists for tenant
        stmt = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.content_hash == content_hash,
            Document.is_deleted == False,  # noqa: E712
        )
        res = await self.session.execute(stmt)
        existing_doc = res.scalar_one_or_none()

        if existing_doc and existing_doc.status in (IngestionStatus.COMPLETED, IngestionStatus.INDEXED):
            logger.info(
                f"[Idempotency] Duplicate file uploaded for tenant '{tenant_id}': "
                f"Document '{existing_doc.id}' already exists with status {existing_doc.status.value}"
            )
            return UploadResponse(
                document_id=existing_doc.id,
                tenant_id=tenant_id,
                status=existing_doc.status,
                s3_uri=existing_doc.s3_raw_uri,
                content_hash=content_hash,
                version_number=existing_doc.version,
                is_duplicate=True,
                event_id="idempotent_skipped",
            )

        # 3. Upload raw file to object storage
        s3_uri = await self.storage.upload_file(
            tenant_id=tenant_id,
            file_name=file_name,
            data=data,
            content_type=mime_type,
        )

        doc_title = title or file_name.rsplit(".", 1)[0].replace("_", " ").title()

        # 4. Create or update Document record in UPLOADED state
        if existing_doc:
            doc = existing_doc
            doc.status = IngestionStatus.UPLOADED
            doc.s3_raw_uri = s3_uri
            doc.failure_reason = None
            doc_version_num = doc.version
            await self.session.commit()
            await self.session.refresh(doc)
        else:
            doc = await self.doc_repo.create(
                tenant_id=tenant_id,
                title=doc_title,
                doc_type=doc_type,
                ticker=ticker,
                content_hash=content_hash,
                s3_raw_uri=s3_uri,
                file_size_bytes=len(data),
                status=IngestionStatus.UPLOADED,
            )
            doc_version_num = 1

        # 5. Build and publish DocumentUploadedEvent to asynchronous queue
        event = DocumentUploadedEvent(
            tenant_id=tenant_id,
            document_id=doc.id,
            version_number=doc_version_num,
            s3_uri=s3_uri,
            file_name=file_name,
            content_hash=content_hash,
            file_size_bytes=len(data),
            mime_type=mime_type,
        )

        event_id = await self.queue.publish(
            queue_name=self.QUEUE_NAME,
            payload=event.to_dict(),
            message_attributes={"tenant_id": tenant_id, "doc_type": doc_type.value},
        )

        logger.info(f"Published document upload event {event_id} for doc '{doc.id}' (URI: {s3_uri})")

        return UploadResponse(
            document_id=doc.id,
            tenant_id=tenant_id,
            status=IngestionStatus.UPLOADED,
            s3_uri=s3_uri,
            content_hash=content_hash,
            version_number=doc_version_num,
            is_duplicate=False,
            event_id=event_id,
        )
