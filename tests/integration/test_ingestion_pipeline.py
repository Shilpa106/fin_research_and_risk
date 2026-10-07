import io
import zipfile

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.ingestion.extractors import (
    CSVExtractor,
    DOCXExtractor,
    ExtractorRegistry,
    HTMLExtractor,
    ImageExtractor,
    PDFExtractor,
)
from src.application.ingestion.pipeline import IngestionPipeline
from src.application.services.ingestion_service import IngestionService
from src.domain.entities import Document, DocumentType, IngestionStatus, Tenant, TenantTier
from src.events.document_events import DocumentUploadedEvent
from src.infrastructure.queue.local_queue import LocalQueueService
from src.infrastructure.storage.local_storage import LocalStorageService
from src.observability.ingestion_metrics import metrics_tracker
from src.workers.ingestion_worker import IngestionWorker


@pytest.fixture(autouse=True)
def reset_metrics():
    metrics_tracker.reset()
    yield
    metrics_tracker.reset()


@pytest.fixture
def local_storage(tmp_path):
    return LocalStorageService(base_dir=tmp_path / "storage")


@pytest.fixture
def local_queue():
    return LocalQueueService(default_visibility_timeout=5, max_retries=2)


async def create_pipeline_tenant(session: AsyncSession, name: str, slug: str) -> Tenant:
    tenant = Tenant(
        name=name,
        slug=slug,
        tier=TenantTier.ENTERPRISE,
        max_rate_limit_rps=2500,
        hitl_threshold_var=0.05,
        is_deleted=False,
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    return tenant


# ==============================================================================
# 1. Multi-Format Extractors Tests
# ==============================================================================

def test_extractors_registry_and_formats():
    """Verify format detection and extraction across PDF, DOCX, HTML, CSV, Images, and scanned PDFs."""
    registry = ExtractorRegistry()

    # 1. HTML Extraction
    html_bytes = b"""
    <html>
        <body>
            <h1>Goldman Sachs Global Macro Outlook</h1>
            <p>We anticipate strong equity performance in Q4.</p>
            <table>
                <tr><th>Metric</th><th>2025</th><th>2026E</th></tr>
                <tr><td>S&P 500 EPS</td><td>$250</td><td>$275</td></tr>
            </table>
        </body>
    </html>
    """
    html_ext = registry.get_extractor("text/html", "outlook.html")
    assert isinstance(html_ext, HTMLExtractor)
    html_res = html_ext.extract(html_bytes, "outlook.html")
    assert "Goldman Sachs Global Macro Outlook" in html_res.text
    assert len(html_res.tables) == 1
    assert html_res.tables[0]["headers"] == ["Metric", "2025", "2026E"]

    # 2. CSV Extraction
    csv_bytes = b"Ticker,Sector,Weight,Return\nAAPL,Technology,0.07,0.18\nMSFT,Technology,0.065,0.15\nJPM,Financials,0.04,0.12\n"
    csv_ext = registry.get_extractor("text/csv", "holdings.csv")
    assert isinstance(csv_ext, CSVExtractor)
    csv_res = csv_ext.extract(csv_bytes, "holdings.csv")
    assert "AAPL" in csv_res.text
    assert len(csv_res.tables[0]["rows"]) == 3

    # 3. DOCX Extraction (synthesize valid Word XML zip)
    docx_buf = io.BytesIO()
    with zipfile.ZipFile(docx_buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                <w:body>
                    <w:p><w:r><w:t>BlackRock Risk Policy Update: Liquidity stress parameters.</w:t></w:r></w:p>
                </w:body>
            </w:document>
            """,
        )
    docx_bytes = docx_buf.getvalue()
    docx_ext = registry.get_extractor("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "policy.docx")
    assert isinstance(docx_ext, DOCXExtractor)
    docx_res = docx_ext.extract(docx_bytes, "policy.docx")
    assert "Liquidity stress parameters" in docx_res.text

    # 4. Standard PDF Extraction
    pdf_bytes = b"%PDF-1.4\nBT /F1 12 Tf (Ticker: NVDA Q3 2026 Earnings Transcript) Tj ET\n%%EOF"
    pdf_ext = registry.get_extractor("application/pdf", "nvda_transcript.pdf")
    assert isinstance(pdf_ext, PDFExtractor)
    pdf_res = pdf_ext.extract(pdf_bytes, "nvda_transcript.pdf")
    assert "NVDA" in pdf_res.text or "Earnings" in pdf_res.text

    # 5. Scanned PDF Extraction (detects low text density and triggers OCR flag)
    scanned_pdf_bytes = b"%PDF-1.4\n/Type /Page /Contents 4 0 R\nstream\n% binary raw image stream without text\nendstream\n%%EOF"
    scanned_res = pdf_ext.extract(scanned_pdf_bytes, "scanned_10k.pdf")
    assert scanned_res.is_scanned is True
    assert scanned_res.ocr_applied is True
    assert "OCR Extracted" in scanned_res.text

    # 6. Image Extraction (PNG/JPEG charts)
    img_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    img_ext = registry.get_extractor("image/png", "chart.png")
    assert isinstance(img_ext, ImageExtractor)
    img_res = img_ext.extract(img_bytes, "chart.png")
    assert img_res.is_scanned is True
    assert img_res.ocr_applied is True
    assert "OCR EXTRACTED IMAGE" in img_res.text


# ==============================================================================
# 2. End-to-End Pipeline Execution
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_document_ingestion(
    async_db_session: AsyncSession,
    local_storage: LocalStorageService,
    local_queue: LocalQueueService,
):
    """Test full pipeline: Upload -> Queue -> Worker -> Stages -> COMPLETED with metrics."""
    tenant = await create_pipeline_tenant(async_db_session, "Bridgewater Associates", "bridgewater")

    # 1. Upload filing via IngestionService
    ingestion_service = IngestionService(storage=local_storage, queue=local_queue, session=async_db_session)
    pdf_content = (
        b"%PDF-1.4\n"
        b"BT (Ticker: AAPL Apple Inc. Fiscal Year 2026 Q3 10-Q Financial Report.) Tj ET\n"
        b"BT (Total Revenue grew 8.4 percent YoY to $85.8 billion driven by Services.) Tj ET\n"
        b"%%EOF"
    )

    upload_res = await ingestion_service.ingest_document(
        tenant_id=tenant.id,
        file_name="AAPL_Q3_2026_10Q.pdf",
        data=pdf_content,
        mime_type="application/pdf",
        doc_type=DocumentType.SEC_10Q,
    )
    assert upload_res.status == IngestionStatus.UPLOADED
    assert upload_res.is_duplicate is False

    # Check queue depth before worker processing
    depth = await local_queue.get_queue_depth(IngestionService.QUEUE_NAME)
    assert depth == 1

    # 2. Run Worker processing
    session_factory = async_sessionmaker(bind=async_db_session.bind, class_=AsyncSession, expire_on_commit=False)
    worker = IngestionWorker(
        queue=local_queue,
        storage=local_storage,
        session_factory=session_factory,
        queue_name=IngestionService.QUEUE_NAME,
    )

    success = await worker.process_one()
    assert success is True

    # 3. Verify Database state
    stmt = select(Document).where(Document.id == upload_res.document_id)
    res = await async_db_session.execute(stmt)
    doc = res.scalar_one()

    assert doc.status == IngestionStatus.COMPLETED
    assert doc.chunk_count >= 1
    assert doc.failure_reason is None

    # 4. Verify Metrics aggregator
    summary = metrics_tracker.get_summary()
    assert summary.documents_processed_total == 1
    assert summary.documents_failed_total == 0
    assert summary.avg_latency_ms > 0


# ==============================================================================
# 3. Idempotency & Duplicate Event Skipping Tests
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_idempotency_duplicate_event_handling(
    async_db_session: AsyncSession,
    local_storage: LocalStorageService,
    local_queue: LocalQueueService,
):
    """
    Critical requirement: If the same document event is received twice,
    the document must not be processed twice unnecessarily.
    """
    tenant = await create_pipeline_tenant(async_db_session, "Two Sigma Investments", "two-sigma")
    ingestion_service = IngestionService(storage=local_storage, queue=local_queue, session=async_db_session)
    session_factory = async_sessionmaker(bind=async_db_session.bind, class_=AsyncSession, expire_on_commit=False)
    worker = IngestionWorker(queue=local_queue, storage=local_storage, session_factory=session_factory)

    csv_data = b"Date,Close,Volume\n2026-10-01,180.5,12000000\n2026-10-02,182.1,14500000\n"

    # Step 1: Initial upload and ingestion
    first_upload = await ingestion_service.ingest_document(
        tenant_id=tenant.id,
        file_name="tsla_prices.csv",
        data=csv_data,
        mime_type="text/csv",
    )
    assert first_upload.is_duplicate is False

    # Process first event through worker
    processed_first = await worker.process_one()
    assert processed_first is True

    metrics_after_first = metrics_tracker.get_summary()
    assert metrics_after_first.documents_processed_total == 1
    assert metrics_after_first.duplicate_events_skipped_total == 0

    # Step 2: Attempt duplicate upload of identical file
    second_upload = await ingestion_service.ingest_document(
        tenant_id=tenant.id,
        file_name="tsla_prices.csv",
        data=csv_data,
        mime_type="text/csv",
    )
    assert second_upload.is_duplicate is True
    assert second_upload.document_id == first_upload.document_id

    # Step 3: Now simulate duplicate event arriving directly in the queue
    duplicate_event = DocumentUploadedEvent(
        tenant_id=tenant.id,
        document_id=first_upload.document_id,
        version_number=1,
        s3_uri=first_upload.s3_uri,
        file_name="tsla_prices.csv",
        content_hash=first_upload.content_hash,
        file_size_bytes=len(csv_data),
        mime_type="text/csv",
    )
    await local_queue.publish(IngestionWorker.DEFAULT_QUEUE_NAME, duplicate_event.to_dict())

    # Worker consumes duplicate event
    processed_duplicate = await worker.process_one()
    assert processed_duplicate is True  # Worker gracefully handled and acknowledged the duplicate

    # Step 4: Verify duplicate was skipped without redundant pipeline execution
    metrics_final = metrics_tracker.get_summary()
    assert metrics_final.documents_processed_total == 1  # Did NOT re-process
    assert metrics_final.duplicate_events_skipped_total == 1  # Correctly recorded as duplicate skipped


# ==============================================================================
# 4. Worker Failure, Retry, Exponential Backoff & DLQ Redrive
# ==============================================================================

class FailingPipeline(IngestionPipeline):
    """Mock pipeline that simulates a persistent downstream failure."""
    async def execute(self, *args, **kwargs):
        raise ConnectionResetError("Embedding API connection timed out to Bedrock")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_failure_retry_and_dead_letter_queue(
    async_db_session: AsyncSession,
    local_storage: LocalStorageService,
    local_queue: LocalQueueService,
):
    """
    Verifies that worker exceptions trigger retry with backoff,
    and upon exhausting retries, route to Dead-Letter Queue (DLQ) with FAILED status and reason.
    """
    tenant = await create_pipeline_tenant(async_db_session, "Citadel Global", "citadel")
    ingestion_service = IngestionService(storage=local_storage, queue=local_queue, session=async_db_session)
    session_factory = async_sessionmaker(bind=async_db_session.bind, class_=AsyncSession, expire_on_commit=False)

    failing_pipeline = FailingPipeline()
    worker = IngestionWorker(
        queue=local_queue,
        storage=local_storage,
        session_factory=session_factory,
        pipeline=failing_pipeline,
        max_retries=2,  # Fail after 2 retries
        base_backoff_seconds=0,
    )

    upload = await ingestion_service.ingest_document(
        tenant_id=tenant.id,
        file_name="corrupt_filing.pdf",
        data=b"%PDF-corrupt",
        mime_type="application/pdf",
    )

    # Attempt 1: Fails -> Requeued (retry_count 0 -> 1)
    res1 = await worker.process_one()
    assert res1 is False
    assert await local_queue.get_queue_depth(IngestionWorker.DEFAULT_QUEUE_NAME) == 1
    assert await local_queue.get_dlq_depth(IngestionWorker.DEFAULT_QUEUE_NAME) == 0

    # Attempt 2: Fails -> Requeued (retry_count 1 -> 2)
    res2 = await worker.process_one()
    assert res2 is False
    assert await local_queue.get_dlq_depth(IngestionWorker.DEFAULT_QUEUE_NAME) == 0

    # Attempt 3: Exhausts max_retries (2) -> Routed to DLQ
    res3 = await worker.process_one()
    assert res3 is False
    assert await local_queue.get_queue_depth(IngestionWorker.DEFAULT_QUEUE_NAME) == 0
    assert await local_queue.get_dlq_depth(IngestionWorker.DEFAULT_QUEUE_NAME) == 1

    # Verify document in DB is marked FAILED with failure reason
    stmt = select(Document).where(Document.id == upload.document_id)
    doc_res = await async_db_session.execute(stmt)
    doc = doc_res.scalar_one()

    assert doc.status == IngestionStatus.FAILED
    assert "ConnectionResetError" in (doc.failure_reason or "")

    # Verify failure metric recorded
    summary = metrics_tracker.get_summary()
    assert summary.documents_failed_total == 1
    assert summary.dlq_depth == 1


# ==============================================================================
# 5. Document Versioning on Content Change
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_document_versioning_lifecycle(
    async_db_session: AsyncSession,
    local_storage: LocalStorageService,
    local_queue: LocalQueueService,
):
    """Verify document version snapshots when a document is updated with new content."""
    tenant = await create_pipeline_tenant(async_db_session, "Point72 Asset Management", "point72")
    session_factory = async_sessionmaker(bind=async_db_session.bind, class_=AsyncSession, expire_on_commit=False)
    worker = IngestionWorker(queue=local_queue, storage=local_storage, session_factory=session_factory)
    ingestion_service = IngestionService(storage=local_storage, queue=local_queue, session=async_db_session)

    # Ingest version 1
    v1_data = b"Apple Inc. initial draft research note."
    v1_upload = await ingestion_service.ingest_document(
        tenant_id=tenant.id,
        file_name="aapl_note.txt",
        data=v1_data,
        mime_type="text/plain",
    )
    await worker.process_one()

    # Query document
    doc = await async_db_session.get(Document, v1_upload.document_id)
    assert doc is not None
    assert doc.version == 1
    assert doc.status == IngestionStatus.COMPLETED

    # Now add version 2 via DocumentRepository.add_version
    v2_data = b"Apple Inc. revised research note with updated valuation model."
    v2_uri = await local_storage.upload_file(tenant.id, "aapl_note_v2.txt", v2_data)
    v2_hash = local_storage.compute_checksum(v2_data)

    v2 = await ingestion_service.doc_repo.add_version(
        tenant_id=tenant.id,
        document_id=doc.id,
        s3_uri=v2_uri,
        content_hash=v2_hash,
        change_summary="Upgraded DCF model",
    )
    assert v2.version_number == 2
    assert doc.version == 2


# ==============================================================================
# 6. Observability Metrics Reporting Test
# ==============================================================================

def test_ingestion_metrics_reporting():
    """Verify metrics tracker aggregates latency percentiles and throughput."""
    metrics_tracker.record_document_completed(latency_ms=120.0)
    metrics_tracker.record_document_completed(latency_ms=180.0)
    metrics_tracker.record_document_completed(latency_ms=250.0)
    metrics_tracker.record_document_failed(reason="Parsing error")
    metrics_tracker.record_duplicate_skipped()
    metrics_tracker.update_queue_depth(15)
    metrics_tracker.update_dlq_depth(2)

    summary = metrics_tracker.get_summary()
    assert summary.documents_processed_total == 3
    assert summary.documents_failed_total == 1
    assert summary.duplicate_events_skipped_total == 1
    assert summary.active_queue_depth == 15
    assert summary.dlq_depth == 2
    assert summary.avg_latency_ms == pytest.approx(183.33, rel=1e-2)
    assert summary.p95_latency_ms == pytest.approx(250.0, rel=1e-2)
    assert summary.throughput_docs_per_minute >= 3.0
