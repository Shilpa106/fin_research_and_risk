import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from ..domain.entities import IngestionStatus


@dataclass
class DocumentUploadedEvent:
    """Event emitted when a raw financial filing or research report is stored in object storage."""
    tenant_id: str
    document_id: str
    version_number: int
    s3_uri: str
    file_name: str
    content_hash: str
    file_size_bytes: int
    mime_type: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    retry_count: int = 0
    idempotency_key: str = field(default="")
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not self.idempotency_key:
            self.idempotency_key = f"{self.tenant_id}:{self.content_hash}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentUploadedEvent":
        parsed = dict(data)
        if isinstance(parsed.get("timestamp"), str):
            parsed["timestamp"] = datetime.fromisoformat(parsed["timestamp"])
        return cls(**parsed)


@dataclass
class DocumentLifecycleEvent:
    """Event published at each stage transition of document ingestion."""
    tenant_id: str
    document_id: str
    status: IngestionStatus
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    failure_reason: str | None = None
    chunk_count: int = 0
    latency_ms: float | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value if isinstance(self.status, IngestionStatus) else str(self.status)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentLifecycleEvent":
        parsed = dict(data)
        if isinstance(parsed.get("timestamp"), str):
            parsed["timestamp"] = datetime.fromisoformat(parsed["timestamp"])
        if isinstance(parsed.get("status"), str):
            parsed["status"] = IngestionStatus(parsed["status"])
        return cls(**parsed)
