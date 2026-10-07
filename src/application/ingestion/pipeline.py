import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ...domain.entities import DocumentType, IngestionStatus
from .extractors import ExtractedDocument, ExtractorRegistry

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """Individual chunk representation for vector retrieval and hybrid indexing."""
    chunk_index: int
    content: str
    token_count: int
    section: str = "body"
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None


@dataclass
class PipelineResult:
    """Execution output of the document ingestion pipeline."""
    document_id: str
    tenant_id: str
    status: IngestionStatus
    chunk_count: int
    total_tokens: int
    doc_type: DocumentType
    extracted_metadata: dict[str, Any]
    latency_ms: float
    failure_reason: str | None = None
    chunks: list[DocumentChunk] = field(default_factory=list)


class IngestionPipeline:
    """
    Multi-stage enterprise financial document ingestion pipeline.
    Executes:
    Classification -> Extraction -> OCR -> Layout -> Metadata -> Chunking -> Embedding -> Indexing -> Validation.
    """

    def __init__(self, extractor_registry: ExtractorRegistry | None = None):
        self.registry = extractor_registry or ExtractorRegistry()

    def classify_document(self, text_or_filename: str) -> DocumentType:
        """Heuristically classifies filing into financial document categories."""
        lower = text_or_filename.lower()
        if "10-k" in lower or "annual report" in lower or "form 10k" in lower:
            return DocumentType.SEC_10K
        if "10-q" in lower or "quarterly report" in lower or "form 10q" in lower:
            return DocumentType.SEC_10Q
        if "8-k" in lower or "current report" in lower or "form 8k" in lower:
            return DocumentType.SEC_8K
        if "earnings" in lower or "call transcript" in lower or "transcript" in lower:
            return DocumentType.EARNINGS_TRANSCRIPT
        if "credit" in lower or "credit memo" in lower or "rating" in lower:
            return DocumentType.CREDIT_MEMO
        if "policy" in lower or "guideline" in lower or "risk" in lower:
            return DocumentType.RISK_POLICY
        return DocumentType.EQUITY_RESEARCH

    def extract_metadata(self, text: str, file_name: str) -> dict[str, Any]:
        """Extracts ticker, fiscal period, fiscal year, and financial attributes."""
        meta: dict[str, Any] = {
            "file_name": file_name,
            "processed_at": datetime.utcnow().isoformat(),
        }

        # 1. Ticker regex: e.g. Ticker: AAPL, Symbol: MSFT, or (NASDAQ: NVDA)
        ticker_match = re.search(r"\b(?:Ticker|Symbol|NYSE|NASDAQ):\s*([A-Z]{1,5})\b", text)
        if ticker_match:
            meta["ticker"] = ticker_match.group(1)
        else:
            # Check filename: AAPL_10K.pdf
            fn_match = re.search(r"\b([A-Z]{1,5})[_\-]", file_name)
            if fn_match:
                meta["ticker"] = fn_match.group(1)

        # 2. Fiscal year: e.g. FY2026, Fiscal Year 2025, 2026 Annual Report
        year_match = re.search(r"\b(?:FY|Fiscal\s+Year|Year\s+Ended\s+[A-Za-z]+\s+\d{1,2},?)\s*(202\d)\b", text, re.IGNORECASE)
        if year_match:
            meta["fiscal_year"] = int(year_match.group(1))

        # 3. Fiscal period: Q1, Q2, Q3, Q4, FY
        period_match = re.search(r"\b(Q[1-4]|FY)\b", text)
        if period_match:
            meta["fiscal_period"] = period_match.group(1).upper()

        return meta

    def process_layout(self, extracted: ExtractedDocument) -> str:
        """Harmonizes layout, cleans excess whitespace, and formats tables."""
        text = extracted.text

        # Format and append tables if not already embedded
        if extracted.tables:
            table_sections = ["\n--- STRUCTURED FINANCIAL TABLES ---"]
            for tbl in extracted.tables:
                headers = tbl.get("headers", [])
                rows = tbl.get("rows", [])
                table_sections.append(f"Table {tbl.get('table_index', 1)}: {' | '.join(str(h) for h in headers)}")
                for r in rows[:20]:
                    table_sections.append(" | ".join(str(c) for c in r))
            text = text + "\n" + "\n".join(table_sections)

        # Normalize line breaks
        cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
        return cleaned

    def chunk_content(
        self,
        text: str,
        target_tokens: int = 500,
        overlap_tokens: int = 50,
        metadata: dict[str, Any] | None = None,
    ) -> list[DocumentChunk]:
        """Recursive semantic chunking preserving paragraph boundaries and table lines."""
        if not text:
            return []

        # Split on paragraph breaks or table dividers
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[DocumentChunk] = []
        current_chunk_paragraphs: list[str] = []
        current_token_count = 0
        chunk_idx = 0

        # Rough approximation: 1 token ~ 4 characters
        for para in paragraphs:
            para_tokens = max(1, len(para) // 4)
            if current_token_count + para_tokens > target_tokens and current_chunk_paragraphs:
                chunk_text = "\n\n".join(current_chunk_paragraphs)
                chunks.append(
                    DocumentChunk(
                        chunk_index=chunk_idx,
                        content=chunk_text,
                        token_count=current_token_count,
                        metadata=dict(metadata or {}),
                    )
                )
                chunk_idx += 1

                # Overlap: keep last paragraph if it fits within overlap_tokens
                if para_tokens <= overlap_tokens:
                    current_chunk_paragraphs = [current_chunk_paragraphs[-1], para]
                    current_token_count = max(1, len(current_chunk_paragraphs[0]) // 4) + para_tokens
                else:
                    current_chunk_paragraphs = [para]
                    current_token_count = para_tokens
            else:
                current_chunk_paragraphs.append(para)
                current_token_count += para_tokens

        if current_chunk_paragraphs:
            chunk_text = "\n\n".join(current_chunk_paragraphs)
            chunks.append(
                DocumentChunk(
                    chunk_index=chunk_idx,
                    content=chunk_text,
                    token_count=current_token_count,
                    metadata=dict(metadata or {}),
                )
            )

        return chunks

    def generate_embeddings(self, chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        """
        Generates vector embeddings for each chunk.
        Uses deterministic normalized vectors (1536 dims) for local/test validation,
        simulating Amazon Titan Embeddings G1 / Bedrock vector outputs.
        """
        import hashlib
        import math

        for chunk in chunks:
            # Generate deterministic 1536-dimensional mock embedding based on chunk text hash
            h = hashlib.sha256(chunk.content.encode("utf-8")).digest()
            raw_vals = [((h[i % len(h)] + i) % 100) / 100.0 - 0.5 for i in range(1536)]
            norm = math.sqrt(sum(x * x for x in raw_vals)) or 1.0
            chunk.embedding = [x / norm for x in raw_vals]

        return chunks

    def validate_pipeline(self, chunks: list[DocumentChunk], metadata: dict[str, Any]) -> bool:
        """Validates that extracted chunks are non-empty and embeddings have correct dimensions."""
        if not chunks:
            return False
        for chunk in chunks:
            if not chunk.content or len(chunk.content.strip()) < 5:
                return False
            if chunk.embedding is None or len(chunk.embedding) != 1536:
                return False
        return True

    async def execute(
        self,
        raw_data: bytes,
        file_name: str,
        mime_type: str,
        document_id: str,
        tenant_id: str,
        status_callback: Callable[[IngestionStatus, str | None], Any] | None = None,
    ) -> PipelineResult:
        """
        Executes the end-to-end ingestion pipeline with stage callbacks.
        Lifecycle: UPLOADED -> PROCESSING -> EXTRACTED -> CHUNKED -> EMBEDDING -> INDEXED -> COMPLETED / FAILED
        """
        start_time = time.perf_counter()

        async def _notify(status: IngestionStatus, reason: str | None = None):
            if status_callback:
                res = status_callback(status, reason)
                if hasattr(res, "__await__"):
                    await res

        try:
            # Stage 1: PROCESSING
            await _notify(IngestionStatus.PROCESSING)

            # Stage 2: Classification
            doc_type = self.classify_document(file_name)

            # Stage 3: Extraction & OCR
            extractor = self.registry.get_extractor(mime_type, file_name)
            extracted = extractor.extract(raw_data, file_name)
            await _notify(IngestionStatus.EXTRACTED)

            # Stage 4: Layout Processing & Metadata Extraction
            cleaned_text = self.process_layout(extracted)
            metadata = self.extract_metadata(cleaned_text, file_name)
            metadata.update(extracted.metadata)
            metadata["is_scanned"] = extracted.is_scanned
            metadata["ocr_applied"] = extracted.ocr_applied
            metadata["page_count"] = extracted.page_count

            # Stage 5: Chunking
            chunks = self.chunk_content(cleaned_text, target_tokens=500, overlap_tokens=50, metadata=metadata)
            await _notify(IngestionStatus.CHUNKED)

            # Stage 6: Embedding
            await _notify(IngestionStatus.EMBEDDING)
            embedded_chunks = self.generate_embeddings(chunks)

            # Stage 7: Indexing & Validation
            await _notify(IngestionStatus.INDEXED)
            is_valid = self.validate_pipeline(embedded_chunks, metadata)
            if not is_valid:
                raise ValueError("Validation failed: chunks were empty or embeddings invalid")

            # Stage 8: COMPLETED
            await _notify(IngestionStatus.COMPLETED)
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            total_tokens = sum(c.token_count for c in embedded_chunks)
            return PipelineResult(
                document_id=document_id,
                tenant_id=tenant_id,
                status=IngestionStatus.COMPLETED,
                chunk_count=len(embedded_chunks),
                total_tokens=total_tokens,
                doc_type=doc_type,
                extracted_metadata=metadata,
                latency_ms=latency_ms,
                chunks=embedded_chunks,
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"Pipeline failed for doc '{document_id}': {error_msg}")
            await _notify(IngestionStatus.FAILED, error_msg)

            return PipelineResult(
                document_id=document_id,
                tenant_id=tenant_id,
                status=IngestionStatus.FAILED,
                chunk_count=0,
                total_tokens=0,
                doc_type=DocumentType.EQUITY_RESEARCH,
                extracted_metadata={},
                latency_ms=latency_ms,
                failure_reason=error_msg,
            )
