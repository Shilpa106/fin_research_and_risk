import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 2.x Declarative Base."""
    pass


class AuditMixin:
    """Audit fields for tracking creation and updates."""
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SoftDeleteMixin:
    """Soft deletion tracking for regulatory auditability."""
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VersionMixin:
    """Optimistic concurrency versioning."""
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


# ==============================================================================
# Role & Permission Enums
# ==============================================================================
class RoleType(str, enum.Enum):
    ADMIN = "ADMIN"
    ADVISOR = "ADVISOR"
    ANALYST = "ANALYST"
    RISK_MANAGER = "RISK_MANAGER"
    READ_ONLY_USER = "READ_ONLY_USER"


class TenantTier(str, enum.Enum):
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"
    SOVEREIGN = "sovereign"


class DocumentType(str, enum.Enum):
    SEC_10K = "10-K"
    SEC_10Q = "10-Q"
    SEC_8K = "8-K"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    EQUITY_RESEARCH = "equity_research"
    CREDIT_MEMO = "credit_memo"
    RISK_POLICY = "risk_policy"


class IngestionStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    EXTRACTED = "EXTRACTED"
    CHUNKED = "CHUNKED"
    EMBEDDING = "EMBEDDING"
    INDEXED = "INDEXED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PENDING = "PENDING"


class HITLReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    IN_REVIEW = "IN_REVIEW"
    MODIFIED = "MODIFIED"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            for member in cls:
                if member.value == value.upper():
                    return member
        return None


class HITLTriggerReason(str, enum.Enum):
    HIGH_RISK_THRESHOLD = "high_risk_threshold"
    COMPLIANCE_RESTRICTION = "compliance_restriction"
    GUARDRAIL_FLAG = "guardrail_flag"
    POLICY_VIOLATION = "policy_violation"
    PORTFOLIO_CONCENTRATION = "portfolio_concentration"


class AuditActionStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    DENIED = "DENIED"
    FAILED = "FAILED"


# ==============================================================================
# Association Tables
# ==============================================================================
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String(36), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("tenant_membership_id", String(36), ForeignKey("tenant_memberships.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


# ==============================================================================
# Identity & Tenant Entities
# ==============================================================================
class Tenant(Base, AuditMixin, SoftDeleteMixin):
    """Institutional client tenant boundary."""
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    tier: Mapped[TenantTier] = mapped_column(Enum(TenantTier), default=TenantTier.ENTERPRISE, nullable=False)
    kms_key_arn: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dedicated_index_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_rate_limit_rps: Mapped[int] = mapped_column(default=1000, nullable=False)
    hitl_threshold_var: Mapped[float] = mapped_column(Float, default=0.05, nullable=False)
    enable_semantic_cache: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    memberships: Mapped[list["TenantMembership"]] = relationship("TenantMembership", back_populates="tenant", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship("Document", back_populates="tenant", cascade="all, delete-orphan")
    api_keys: Mapped[list["TenantApiKey"]] = relationship("TenantApiKey", back_populates="tenant", cascade="all, delete-orphan")
    portfolios: Mapped[list["Portfolio"]] = relationship("Portfolio", back_populates="tenant", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship("Conversation", back_populates="tenant", cascade="all, delete-orphan")
    agent_runs: Mapped[list["AgentRun"]] = relationship("AgentRun", back_populates="tenant", cascade="all, delete-orphan")
    evaluation_runs: Mapped[list["EvaluationRun"]] = relationship("EvaluationRun", back_populates="tenant", cascade="all, delete-orphan")


class User(Base, AuditMixin, SoftDeleteMixin):
    """Platform user entity across tenants."""
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    memberships: Mapped[list["TenantMembership"]] = relationship("TenantMembership", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")


class Role(Base, AuditMixin):
    """RBAC Role entity."""
    __tablename__ = "roles"

    name: Mapped[RoleType] = mapped_column(Enum(RoleType), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False)

    permissions: Mapped[list["Permission"]] = relationship("Permission", secondary=role_permissions, back_populates="roles")
    memberships: Mapped[list["TenantMembership"]] = relationship("TenantMembership", secondary=user_roles, back_populates="roles")


class Permission(Base, AuditMixin):
    """Fine-grained permission entity."""
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False)

    roles: Mapped[list["Role"]] = relationship("Role", secondary=role_permissions, back_populates="permissions")


class TenantMembership(Base, AuditMixin):
    """Binds a User to a Tenant with specific Roles."""
    __tablename__ = "tenant_memberships"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="memberships")
    user: Mapped["User"] = relationship("User", back_populates="memberships")
    roles: Mapped[list["Role"]] = relationship("Role", secondary=user_roles, back_populates="memberships")

    __table_args__ = (
        Index("idx_tenant_membership_unique", "tenant_id", "user_id", unique=True),
    )


class RefreshToken(Base, AuditMixin):
    """Rotating cryptographically hashed refresh tokens with reuse detection."""
    __tablename__ = "refresh_tokens"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    family_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")


class TenantApiKey(Base, AuditMixin):
    """Machine-to-machine API key."""
    __tablename__ = "tenant_api_keys"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[RoleType] = mapped_column(Enum(RoleType), default=RoleType.ANALYST, nullable=False)
    rate_limit_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="api_keys")


# ==============================================================================
# Transactional Data Layer Entities
# ==============================================================================

class Conversation(Base, AuditMixin, SoftDeleteMixin, VersionMixin):
    """Agent conversation session scoped to tenant."""
    __tablename__ = "conversations"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="conversations")
    user: Mapped["User"] = relationship("User", back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at", lazy="selectin")
    agent_runs: Mapped[list["AgentRun"]] = relationship("AgentRun", back_populates="conversation")

    __table_args__ = (
        Index("idx_conv_tenant_user_active", "tenant_id", "user_id", "is_deleted"),
        Index("idx_conv_tenant_created", "tenant_id", "created_at"),
    )


# Alias for backward compatibility
ConversationThread = Conversation


class Message(Base, AuditMixin, SoftDeleteMixin):
    """Individual dialogue turn inside a conversation."""
    __tablename__ = "messages"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user, assistant, system, tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    citations_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("idx_msg_conv_created", "conversation_id", "created_at"),
        Index("idx_msg_tenant_created", "tenant_id", "created_at"),
    )


class Document(Base, AuditMixin, SoftDeleteMixin, VersionMixin):
    """Financial document catalog entity."""
    __tablename__ = "documents"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    doc_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), index=True, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(10), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_raw_uri: Mapped[str] = mapped_column(String(1024), default="s3://default/path", nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[IngestionStatus] = mapped_column(Enum(IngestionStatus), default=IngestionStatus.UPLOADED, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan", lazy="selectin")
    metadata_items: Mapped[list["DocumentMetadata"]] = relationship("DocumentMetadata", back_populates="document", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_doc_tenant_content_hash", "tenant_id", "content_hash", unique=True),
        Index("idx_doc_tenant_ticker", "tenant_id", "ticker", "is_deleted"),
        Index("idx_doc_tenant_doctype", "tenant_id", "doc_type", "is_deleted"),
    )


# Alias for backward compatibility
FinancialDocument = Document


class DocumentVersion(Base, AuditMixin):
    """Immutable version snapshot for documents."""
    __tablename__ = "document_versions"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    s3_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[IngestionStatus] = mapped_column(Enum(IngestionStatus), default=IngestionStatus.UPLOADED, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="versions")

    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_doc_version"),
        Index("idx_doc_version_tenant", "tenant_id", "document_id"),
    )


class DocumentMetadata(Base, AuditMixin):
    """Structured key-value metadata associated with a financial filing."""
    __tablename__ = "document_metadata"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    meta_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    meta_value: Mapped[str] = mapped_column(Text, nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), default="string", nullable=False)

    document: Mapped["Document"] = relationship("Document", back_populates="metadata_items")

    __table_args__ = (
        UniqueConstraint("document_id", "meta_key", name="uq_doc_metadata_key"),
        Index("idx_doc_meta_tenant_key", "tenant_id", "meta_key"),
    )


class Portfolio(Base, AuditMixin, SoftDeleteMixin, VersionMixin):
    """Institutional portfolio holdings and risk parameters scoped to tenant."""
    __tablename__ = "portfolios"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    benchmark: Mapped[str] = mapped_column(String(20), default="SPY", nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    total_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    positions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="portfolios")
    holdings: Mapped[list["Holding"]] = relationship("Holding", back_populates="portfolio", cascade="all, delete-orphan", lazy="selectin")
    risk_assessments: Mapped[list["RiskAssessment"]] = relationship("RiskAssessment", back_populates="portfolio", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_port_tenant_name", "tenant_id", "name", "is_deleted"),
        Index("idx_port_tenant_created", "tenant_id", "created_at"),
    )


class Holding(Base, AuditMixin):
    """Individual security holding position inside a portfolio."""
    __tablename__ = "holdings"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    asset_class: Mapped[str] = mapped_column(String(50), default="EQUITY", nullable=False)
    shares: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    market_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    market_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_basis: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    portfolio: Mapped["Portfolio"] = relationship("Portfolio", back_populates="holdings")

    __table_args__ = (
        UniqueConstraint("portfolio_id", "ticker", name="uq_portfolio_ticker"),
        Index("idx_holding_tenant_ticker", "tenant_id", "ticker"),
    )


class RiskAssessment(Base, AuditMixin):
    """Quantitative risk modeling metrics (VaR, stress tests, scenario analysis)."""
    __tablename__ = "risk_assessments"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id: Mapped[str] = mapped_column(String(36), ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_type: Mapped[str] = mapped_column(String(50), default="VAR", nullable=False)  # VAR, STRESS_TEST, SCENARIO
    confidence_level: Mapped[float] = mapped_column(Float, default=0.99, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    rating: Mapped[str] = mapped_column(String(20), default="LOW", nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    requires_hitl: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    portfolio: Mapped["Portfolio"] = relationship("Portfolio", back_populates="risk_assessments")

    __table_args__ = (
        Index("idx_risk_tenant_portfolio", "tenant_id", "portfolio_id"),
        Index("idx_risk_tenant_created", "tenant_id", "created_at"),
    )


class AgentRun(Base, AuditMixin):
    """Multi-agent reasoning workflow tracking."""
    __tablename__ = "agent_runs"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False, index=True)
    input_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="agent_runs")
    conversation: Mapped["Conversation | None"] = relationship("Conversation", back_populates="agent_runs")
    tool_executions: Mapped[list["ToolExecution"]] = relationship("ToolExecution", back_populates="agent_run", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_agent_run_tenant_status", "tenant_id", "status"),
        Index("idx_agent_run_tenant_created", "tenant_id", "created_at"),
    )


class ToolExecution(Base, AuditMixin):
    """Execution audit trail for tools called by multi-agent reasoning graphs."""
    __tablename__ = "tool_executions"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    input_parameters_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    output_result_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="SUCCESS", nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    agent_run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="tool_executions")

    __table_args__ = (
        Index("idx_tool_exec_tenant_tool", "tenant_id", "tool_name"),
        Index("idx_tool_exec_tenant_created", "tenant_id", "created_at"),
    )


class AuditEvent(Base, AuditMixin):
    """Immutable audit event for security and regulatory compliance."""
    __tablename__ = "audit_events"

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[AuditActionStatus] = mapped_column(Enum(AuditActionStatus), nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_audit_tenant_action", "tenant_id", "action"),
        Index("idx_audit_tenant_created", "tenant_id", "created_at"),
    )


# Alias for backward compatibility
SecurityAuditEvent = AuditEvent


class EvaluationRun(Base, AuditMixin):
    """Evaluation benchmark run for guardrails, hallucinations, and faithfulness."""
    __tablename__ = "evaluation_runs"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    faithfulness_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    answer_relevance_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    hallucination_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_eval_samples: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED", nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="evaluation_runs")

    __table_args__ = (
        Index("idx_eval_tenant_dataset", "tenant_id", "dataset_name"),
        Index("idx_eval_tenant_created", "tenant_id", "created_at"),
    )


class HITLReviewTask(Base, AuditMixin, VersionMixin):
    """
    Human-in-the-Loop review and approval task for high-impact financial operations.
    Enforces role authorization, immutable auditability, and optimistic concurrency versioning.
    """
    __tablename__ = "hitl_review_tasks"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    thread_id: Mapped[str] = mapped_column(String(255), default="default-thread", nullable=False, index=True)
    agent_run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)

    trigger_reason: Mapped[HITLTriggerReason] = mapped_column(Enum(HITLTriggerReason), default=HITLTriggerReason.HIGH_RISK_THRESHOLD, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSON, default=dict, nullable=False)
    model_output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    proposed_action: Mapped[str] = mapped_column(String(100), default="rebalance_portfolio", nullable=False)
    tool_calls: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[HITLReviewStatus] = mapped_column(Enum(HITLReviewStatus), default=HITLReviewStatus.PENDING, nullable=False, index=True)

    assigned_reviewer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewer_decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Legacy compatibility fields
    original_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_report_draft: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_hitl_tenant_status", "tenant_id", "status"),
        Index("idx_hitl_tenant_created", "tenant_id", "created_at"),
        Index("idx_hitl_expires", "expires_at"),
    )

