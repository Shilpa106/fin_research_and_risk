from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthComponentStatus(BaseModel):
    status: str
    details: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ReadinessResponse(BaseModel):
    status: str
    database: HealthComponentStatus
    redis: HealthComponentStatus
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LivenessResponse(BaseModel):
    status: str = "ok"


class ErrorResponse(BaseModel):
    error: str
    message: str
    status_code: int
    correlation_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    tenant_id: str
    user_id: str
    role: str


class LoginRequest(BaseModel):
    email: str
    password: str
    tenant_slug: str


class CitationDto(BaseModel):
    chunk_id: str
    ticker: str | None = None
    doc_type: str
    fiscal_period: str | None = None
    section_name: str | None = None
    score: float
    snippet: str


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=5000)
    thread_id: str | None = None
    tickers: list[str] = Field(default_factory=list)
    stream: bool = False


class ChatResponse(BaseModel):
    thread_id: str
    query: str
    response: str
    citations: list[CitationDto] = Field(default_factory=list)
    requires_hitl: bool = False
    hitl_task_id: str | None = None
    cached: bool = False


class SearchRequest(BaseModel):
    query: str
    tickers: list[str] | None = None
    top_k: int = 10
    alpha: float = 0.6


class ChunkDto(BaseModel):
    chunk_id: str
    ticker: str | None
    title: str
    doc_type: str
    section_name: str | None
    content: str
    score: float


class SearchResponse(BaseModel):
    total_hits: int
    took_ms: float
    results: list[ChunkDto]


class PortfolioPositionDto(BaseModel):
    ticker: str
    market_value: float
    weight: float


class VaRRequest(BaseModel):
    positions: list[PortfolioPositionDto]
    confidence_level: float = 0.99
    horizon_days: int = 20


class VaRResponse(BaseModel):
    total_market_value: float
    var_daily_pct: float
    var_amount_usd: float
    risk_rating: str
    requires_hitl: bool


class HITLActionRequest(BaseModel):
    action: str = Field(..., description="APPROVE | REJECT | MODIFY")
    reviewer_notes: str | None = None
    modified_content: str | None = None


class HITLTaskDto(BaseModel):
    task_id: str
    tenant_id: str
    thread_id: str
    trigger_reason: str
    risk_score: float | None
    status: str
    original_query: str
    generated_report_draft: str
    created_at: datetime


class DocumentCreateDto(BaseModel):
    title: str
    ticker: str | None = None
    doc_type: str = "10-K"
    content: str = ""
    content_hash: str = ""


class DocumentResponseDto(BaseModel):
    id: str
    tenant_id: str
    title: str
    ticker: str | None = None
    doc_type: str
    content: str | None = None


class ConversationCreateDto(BaseModel):
    title: str


class ConversationResponseDto(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    title: str
    is_archived: bool


class PortfolioCreateDto(BaseModel):
    name: str
    benchmark: str = "SPY"
    total_value: float = 0.0
    positions_json: str = "[]"
    description: str = ""


class PortfolioResponseDto(BaseModel):
    id: str
    tenant_id: str
    name: str
    benchmark: str
    total_value: float
    positions_json: str
    description: str | None = None

