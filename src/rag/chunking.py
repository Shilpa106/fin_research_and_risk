import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from ..domain.entities import DocumentType


@dataclass
class FinancialChunk:
    """
    Standardized institutional chunk retention model.
    Retains mandatory provenance, security permissions, and financial layout context.
    """
    chunk_id: str
    document_id: str
    document_version: int
    tenant_id: str
    content: str
    page: int
    section: str
    source: str
    timestamp: datetime
    permissions: list[str] = field(default_factory=lambda: ["ANALYST", "ADVISOR", "ADMIN", "RISK_MANAGER", "READ_ONLY_USER"])
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FinancialChunk":
        parsed = dict(data)
        if isinstance(parsed.get("timestamp"), str):
            parsed["timestamp"] = datetime.fromisoformat(parsed["timestamp"])
        return cls(**parsed)


# ==============================================================================
# Chunking Strategy Implementations
# ==============================================================================

class RecursiveProseChunker:
    """Standard recursive text chunking respecting paragraph and sentence boundaries."""

    def __init__(self, target_tokens: int = 400, overlap_tokens: int = 40):
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(
        self,
        text: str,
        document_id: str,
        document_version: int,
        tenant_id: str,
        source: str,
        permissions: list[str] | None = None,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[FinancialChunk]:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[FinancialChunk] = []
        current_paragraphs: list[str] = []
        current_tokens = 0
        chunk_idx = 0
        current_page = 1

        for para in paragraphs:
            # Check for page markers
            if "--- Page " in para:
                page_match = re.search(r"--- Page (\d+) ---", para)
                if page_match:
                    current_page = int(page_match.group(1))

            para_tokens = max(1, len(para) // 4)
            if current_tokens + para_tokens > self.target_tokens and current_paragraphs:
                content = "\n\n".join(current_paragraphs)
                chunks.append(
                    FinancialChunk(
                        chunk_id=f"{document_id}_c{chunk_idx}",
                        document_id=document_id,
                        document_version=document_version,
                        tenant_id=tenant_id,
                        content=content,
                        page=current_page,
                        section="Prose",
                        source=source,
                        timestamp=datetime.utcnow(),
                        permissions=permissions or ["ANALYST", "ADVISOR", "ADMIN", "RISK_MANAGER", "READ_ONLY_USER"],
                        metadata=dict(base_metadata or {}),
                    )
                )
                chunk_idx += 1
                current_paragraphs = [current_paragraphs[-1], para] if para_tokens <= self.overlap_tokens else [para]
                current_tokens = sum(max(1, len(p) // 4) for p in current_paragraphs)
            else:
                current_paragraphs.append(para)
                current_tokens += para_tokens

        if current_paragraphs:
            content = "\n\n".join(current_paragraphs)
            chunks.append(
                FinancialChunk(
                    chunk_id=f"{document_id}_c{chunk_idx}",
                    document_id=document_id,
                    document_version=document_version,
                    tenant_id=tenant_id,
                    content=content,
                    page=current_page,
                    section="Prose",
                    source=source,
                    timestamp=datetime.utcnow(),
                    permissions=permissions or ["ANALYST", "ADVISOR", "ADMIN", "RISK_MANAGER", "READ_ONLY_USER"],
                    metadata=dict(base_metadata or {}),
                )
            )

        return chunks


class SectionAwareReportChunker:
    """Splits institutional filings preserving SEC items and research report sections."""

    SECTION_PATTERNS = [
        r"(?:Item\s+(?:1A|1B|1|2|3|4|5|6|7A|7|8|9|10)\.?\s+[A-Za-z\s]{3,50})",
        r"(?:Executive\s+Summary|Management'?s\s+Discussion|Risk\s+Factors|Financial\s+Statements|Macro\s+Outlook)",
        r"(?:Valuation\s+Methodology|Price\s+Target\s+Summary|Rating\s+Rationale)",
    ]

    def chunk(
        self,
        text: str,
        document_id: str,
        document_version: int,
        tenant_id: str,
        source: str,
        permissions: list[str] | None = None,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[FinancialChunk]:
        combined_pattern = "|".join(self.SECTION_PATTERNS)
        splits = re.split(f"({combined_pattern})", text, flags=re.IGNORECASE)

        chunks: list[FinancialChunk] = []
        current_section = "General Overview"
        chunk_idx = 0

        for part in splits:
            part = part.strip()
            if not part:
                continue

            # Check if this part is a section header
            if any(re.match(p, part, re.IGNORECASE) for p in self.SECTION_PATTERNS):
                current_section = part.title()
                continue

            # Split larger sections into 400 token windows preserving section header
            sub_chunker = RecursiveProseChunker(target_tokens=450, overlap_tokens=40)
            sub_chunks = sub_chunker.chunk(
                text=part,
                document_id=document_id,
                document_version=document_version,
                tenant_id=tenant_id,
                source=source,
                permissions=permissions,
                base_metadata=base_metadata,
            )
            for sc in sub_chunks:
                sc.chunk_id = f"{document_id}_s{chunk_idx}"
                sc.section = current_section
                sc.content = f"[{current_section}]\n{sc.content}"
                chunks.append(sc)
                chunk_idx += 1

        return chunks or RecursiveProseChunker().chunk(
            text, document_id, document_version, tenant_id, source, permissions, base_metadata
        )


class SpeakerAwareTranscriptChunker:
    """Segments earnings calls by speaker turns (CEO, CFO, Analysts, Q&A)."""

    SPEAKER_PATTERN = r"(^[A-Z][a-zA-Z\s\.\-]{2,30}(?:\s*—|\s*-\s*|\s*:\s*)(?:CEO|CFO|COO|President|Analyst|Operator|Executive|[A-Za-z\s]+)?(?::|\b))"

    def chunk(
        self,
        text: str,
        document_id: str,
        document_version: int,
        tenant_id: str,
        source: str,
        permissions: list[str] | None = None,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[FinancialChunk]:
        lines = text.split("\n")
        chunks: list[FinancialChunk] = []
        current_speaker = "Executive Remarks"
        current_dialogue: list[str] = []
        chunk_idx = 0

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Detect speaker prefix
            speaker_match = re.match(r"^([A-Z][a-zA-Z\s\.\-]{2,25}(?:\s*\(.*?\))?\s*:\s*)", line_str)
            if speaker_match:
                if current_dialogue:
                    content = "\n".join(current_dialogue)
                    chunks.append(
                        FinancialChunk(
                            chunk_id=f"{document_id}_spk{chunk_idx}",
                            document_id=document_id,
                            document_version=document_version,
                            tenant_id=tenant_id,
                            content=f"[{current_speaker}]\n{content}",
                            page=1,
                            section=f"Transcript: {current_speaker}",
                            source=source,
                            timestamp=datetime.utcnow(),
                            permissions=permissions or ["ANALYST", "ADVISOR", "ADMIN", "RISK_MANAGER", "READ_ONLY_USER"],
                            metadata={**(base_metadata or {}), "speaker": current_speaker},
                        )
                    )
                    chunk_idx += 1
                    current_dialogue = []

                current_speaker = speaker_match.group(1).rstrip(": ")
                current_dialogue.append(line_str)
            else:
                current_dialogue.append(line_str)

        if current_dialogue:
            content = "\n".join(current_dialogue)
            chunks.append(
                FinancialChunk(
                    chunk_id=f"{document_id}_spk{chunk_idx}",
                    document_id=document_id,
                    document_version=document_version,
                    tenant_id=tenant_id,
                    content=f"[{current_speaker}]\n{content}",
                    page=1,
                    section=f"Transcript: {current_speaker}",
                    source=source,
                    timestamp=datetime.utcnow(),
                    permissions=permissions or ["ANALYST", "ADVISOR", "ADMIN", "RISK_MANAGER", "READ_ONLY_USER"],
                    metadata={**(base_metadata or {}), "speaker": current_speaker},
                )
            )

        return chunks or RecursiveProseChunker().chunk(
            text, document_id, document_version, tenant_id, source, permissions, base_metadata
        )


class TableAwareFinancialChunker:
    """Segments financial tables row-by-row preserving column headers and summaries."""

    def chunk(
        self,
        text: str,
        document_id: str,
        document_version: int,
        tenant_id: str,
        source: str,
        permissions: list[str] | None = None,
        base_metadata: dict[str, Any] | None = None,
        rows_per_chunk: int = 8,
    ) -> list[FinancialChunk]:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        header_line = lines[0] if lines else "Table Header"
        data_rows = lines[1:] if len(lines) > 1 else lines

        chunks: list[FinancialChunk] = []
        chunk_idx = 0

        for i in range(0, len(data_rows), rows_per_chunk):
            batch = data_rows[i : i + rows_per_chunk]
            content = f"[Financial Table]\n{header_line}\n" + "\n".join(batch)
            chunks.append(
                FinancialChunk(
                    chunk_id=f"{document_id}_tbl{chunk_idx}",
                    document_id=document_id,
                    document_version=document_version,
                    tenant_id=tenant_id,
                    content=content,
                    page=1,
                    section="Financial Table",
                    source=source,
                    timestamp=datetime.utcnow(),
                    permissions=permissions or ["ANALYST", "ADVISOR", "ADMIN", "RISK_MANAGER", "READ_ONLY_USER"],
                    metadata={**(base_metadata or {}), "row_start": i, "row_end": i + len(batch)},
                )
            )
            chunk_idx += 1

        return chunks


class PolicySectionChunker:
    """Segments compliance policies and risk guidelines by numbered sections and clauses."""

    POLICY_HEADER_PATTERN = r"(?:Section\s+\d+(?:\.\d+)*|Clause\s+\d+|Article\s+[IVXLCDM]+|Policy\s+\d+)"

    def chunk(
        self,
        text: str,
        document_id: str,
        document_version: int,
        tenant_id: str,
        source: str,
        permissions: list[str] | None = None,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[FinancialChunk]:
        sections = re.split(rf"(?m)^(?={self.POLICY_HEADER_PATTERN})", text)
        chunks: list[FinancialChunk] = []
        chunk_idx = 0

        for sec in sections:
            sec_clean = sec.strip()
            if not sec_clean:
                continue

            first_line = sec_clean.split("\n")[0]
            section_title = first_line[:60].strip()

            chunks.append(
                FinancialChunk(
                    chunk_id=f"{document_id}_pol{chunk_idx}",
                    document_id=document_id,
                    document_version=document_version,
                    tenant_id=tenant_id,
                    content=f"[{section_title}]\n{sec_clean}",
                    page=1,
                    section=section_title,
                    source=source,
                    timestamp=datetime.utcnow(),
                    permissions=permissions or ["RISK_MANAGER", "ADMIN", "ANALYST"],
                    metadata={**(base_metadata or {}), "policy_section": section_title},
                )
            )
            chunk_idx += 1

        return chunks or RecursiveProseChunker().chunk(
            text, document_id, document_version, tenant_id, source, permissions, base_metadata
        )


class CompositeChunker:
    """Dispatches to the optimal domain chunker based on DocumentType."""

    def __init__(self):
        self.prose_chunker = RecursiveProseChunker()
        self.report_chunker = SectionAwareReportChunker()
        self.transcript_chunker = SpeakerAwareTranscriptChunker()
        self.table_chunker = TableAwareFinancialChunker()
        self.policy_chunker = PolicySectionChunker()

    def chunk_document(
        self,
        text: str,
        doc_type: DocumentType,
        document_id: str,
        document_version: int,
        tenant_id: str,
        source: str,
        permissions: list[str] | None = None,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[FinancialChunk]:
        if doc_type == DocumentType.EARNINGS_TRANSCRIPT:
            return self.transcript_chunker.chunk(text, document_id, document_version, tenant_id, source, permissions, base_metadata)
        elif doc_type in (DocumentType.SEC_10K, DocumentType.SEC_10Q, DocumentType.SEC_8K, DocumentType.EQUITY_RESEARCH):
            return self.report_chunker.chunk(text, document_id, document_version, tenant_id, source, permissions, base_metadata)
        elif doc_type == DocumentType.RISK_POLICY:
            return self.policy_chunker.chunk(text, document_id, document_version, tenant_id, source, permissions, base_metadata)
        elif "Table Headers:" in text or " | " in text:
            return self.table_chunker.chunk(text, document_id, document_version, tenant_id, source, permissions, base_metadata)
        return self.prose_chunker.chunk(text, document_id, document_version, tenant_id, source, permissions, base_metadata)
