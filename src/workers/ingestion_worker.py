import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..application.ingestion.pipeline import IngestionPipeline
from ..domain.entities import Document, DocumentVersion, IngestionStatus
from ..events.document_events import DocumentUploadedEvent
from ..interfaces.queue import MessageQueue, QueueMessage
from ..interfaces.storage import ObjectStorageService
from ..observability.ingestion_metrics import metrics_tracker

logger = logging.getLogger(__name__)


class IngestionWorker:
    """
    Asynchronous event-driven document ingestion worker.
    Features:
    - Queue consumption with batching
    - Strict content-hash idempotency
    - Multi-stage pipeline execution
    - Exponential backoff retry handling
    - Dead-Letter Queue (DLQ) isolation
    - Comprehensive metrics tracking
    """

    DEFAULT_QUEUE_NAME = "financial-document-ingestion"

    def __init__(
        self,
        queue: MessageQueue,
        storage: ObjectStorageService,
        session_factory: async_sessionmaker[AsyncSession],
        pipeline: IngestionPipeline | None = None,
        queue_name: str = DEFAULT_QUEUE_NAME,
        max_retries: int = 3,
        base_backoff_seconds: int = 2,
    ):
        self.queue = queue
        self.storage = storage
        self.session_factory = session_factory
        self.pipeline = pipeline or IngestionPipeline()
        self.queue_name = queue_name
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._in_flight_keys: set[str] = set()

    async def _update_document_status(
        self,
        session: AsyncSession,
        document_id: str,
        status: IngestionStatus,
        failure_reason: str | None = None,
        chunk_count: int | None = None,
    ) -> None:
        """Updates document and current version status in PostgreSQL."""
        stmt = select(Document).where(Document.id == document_id)
        result = await session.execute(stmt)
        doc = result.scalar_one_or_none()
        if not doc:
            return

        doc.status = status
        if failure_reason is not None:
            doc.failure_reason = failure_reason
        if chunk_count is not None:
            doc.chunk_count = chunk_count

        if doc.current_version_id:
            ver_stmt = select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
            ver_result = await session.execute(ver_stmt)
            ver = ver_result.scalar_one_or_none()
            if ver:
                ver.status = status
                if failure_reason is not None:
                    ver.failure_reason = failure_reason
                if chunk_count is not None:
                    ver.chunk_count = chunk_count

        await session.commit()

    async def handle_message(self, message: QueueMessage) -> bool:
        """
        Processes an individual document uploaded event with strict idempotency and DLQ handling.
        Returns True if successfully processed or skipped due to idempotency, False if failed.
        """
        event = DocumentUploadedEvent.from_dict(message.payload)
        idempotency_key = event.idempotency_key

        # 1. In-flight concurrency lock check
        if idempotency_key in self._in_flight_keys:
            logger.info(f"Document {event.document_id} is already in-flight; delaying message.")
            await self.queue.nack(self.queue_name, message.receipt_handle, requeue=True, backoff_seconds=2)
            return False

        self._in_flight_keys.add(idempotency_key)

        try:
            async with self.session_factory() as session:
                # 2. Database idempotency check: has this document/hash already reached completion?
                stmt = select(Document).where(Document.id == event.document_id)
                res = await session.execute(stmt)
                doc = res.scalar_one_or_none()

                if doc and doc.status in (IngestionStatus.COMPLETED, IngestionStatus.INDEXED):
                    logger.info(
                        f"[Idempotency] Document '{event.document_id}' (hash: {event.content_hash[:10]}) "
                        f"is already {doc.status.value}. Skipping redundant ingestion."
                    )
                    metrics_tracker.record_duplicate_skipped(event.tenant_id)
                    await self.queue.ack(self.queue_name, message.receipt_handle)
                    return True

                # Also check if another document in the same tenant has the exact same content_hash and is completed
                hash_stmt = select(Document).where(
                    Document.tenant_id == event.tenant_id,
                    Document.content_hash == event.content_hash,
                    Document.id != event.document_id,
                    Document.status == IngestionStatus.COMPLETED,
                )
                hash_res = await session.execute(hash_stmt)
                existing_completed = hash_res.scalar_one_or_none()

                if existing_completed:
                    logger.info(
                        f"[Idempotency] Identical content hash already processed under Document '{existing_completed.id}'. "
                        f"Marking Document '{event.document_id}' as COMPLETED."
                    )
                    await self._update_document_status(
                        session,
                        event.document_id,
                        IngestionStatus.COMPLETED,
                        chunk_count=existing_completed.chunk_count,
                    )
                    metrics_tracker.record_duplicate_skipped(event.tenant_id)
                    await self.queue.ack(self.queue_name, message.receipt_handle)
                    return True

                # 3. Mark document as PROCESSING
                await self._update_document_status(session, event.document_id, IngestionStatus.PROCESSING)

                # 4. Download document binary from storage
                raw_bytes = await self.storage.download_file(event.s3_uri)

                # Callback to persist intermediate states to DB
                async def _on_status_change(status: IngestionStatus, reason: str | None = None):
                    async with self.session_factory() as inner_session:
                        await self._update_document_status(inner_session, event.document_id, status, failure_reason=reason)

                # 5. Run the multi-stage pipeline
                result = await self.pipeline.execute(
                    raw_data=raw_bytes,
                    file_name=event.file_name,
                    mime_type=event.mime_type,
                    document_id=event.document_id,
                    tenant_id=event.tenant_id,
                    status_callback=_on_status_change,
                )

                if result.status == IngestionStatus.COMPLETED:
                    await self._update_document_status(
                        session,
                        event.document_id,
                        IngestionStatus.COMPLETED,
                        chunk_count=result.chunk_count,
                    )
                    metrics_tracker.record_document_completed(result.latency_ms, event.tenant_id)
                    await self.queue.ack(self.queue_name, message.receipt_handle)
                    logger.info(f"Successfully completed ingestion for doc '{event.document_id}' in {result.latency_ms:.1f}ms")
                    return True
                else:
                    raise RuntimeError(result.failure_reason or "Pipeline execution returned failed status")

        except Exception as e:
            error_reason = f"{type(e).__name__}: {str(e)}"
            logger.error(f"Error processing message {message.id} for doc {event.document_id}: {error_reason}")

            # 6. Retry & Dead-Letter handling
            if message.retry_count >= self.max_retries:
                logger.error(f"Message {message.id} exceeded max retries ({self.max_retries}) -> Routing to DLQ")
                await self.queue.send_to_dead_letter(self.queue_name, message, error_reason)
                async with self.session_factory() as fail_session:
                    await self._update_document_status(
                        fail_session,
                        event.document_id,
                        IngestionStatus.FAILED,
                        failure_reason=error_reason,
                    )
                metrics_tracker.record_document_failed(error_reason, event.tenant_id)
            else:
                backoff_delay = self.base_backoff_seconds * (2 ** message.retry_count)
                logger.warning(f"Requeueing message {message.id} with exponential backoff delay of {backoff_delay}s")
                await self.queue.nack(
                    self.queue_name,
                    message.receipt_handle,
                    requeue=True,
                    backoff_seconds=backoff_delay,
                )

            return False

        finally:
            self._in_flight_keys.discard(idempotency_key)

    async def process_one(self) -> bool:
        """Pulls and processes a single message from the queue. Useful for synchronous step execution."""
        messages = await self.queue.consume(self.queue_name, batch_size=1)
        if not messages:
            return False

        msg = messages[0]
        res = await self.handle_message(msg)

        # Update gauge metrics
        q_depth = await self.queue.get_queue_depth(self.queue_name)
        dlq_depth = await self.queue.get_dlq_depth(self.queue_name)
        metrics_tracker.update_queue_depth(q_depth)
        metrics_tracker.update_dlq_depth(dlq_depth)

        return res

    async def process_batch(self, batch_size: int = 10) -> int:
        """Pulls and processes a batch of messages. Returns count of processed messages."""
        messages = await self.queue.consume(self.queue_name, batch_size=batch_size)
        processed = 0
        for msg in messages:
            success = await self.handle_message(msg)
            if success:
                processed += 1

        # Update gauge metrics
        q_depth = await self.queue.get_queue_depth(self.queue_name)
        dlq_depth = await self.queue.get_dlq_depth(self.queue_name)
        metrics_tracker.update_queue_depth(q_depth)
        metrics_tracker.update_dlq_depth(dlq_depth)

        return processed

    async def run(self, stop_event: asyncio.Event, poll_interval: float = 0.5) -> None:
        """Background continuous worker loop."""
        logger.info(f"Starting IngestionWorker loop on queue '{self.queue_name}'...")
        while not stop_event.is_set():
            try:
                processed = await self.process_batch(batch_size=10)
                if processed == 0:
                    await asyncio.sleep(poll_interval)
            except Exception as e:
                logger.error(f"Unexpected error in IngestionWorker loop: {e}", exc_info=True)
                await asyncio.sleep(poll_interval)
