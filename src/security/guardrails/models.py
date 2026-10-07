import enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ==============================================================================
# Security Classification & Violation Enums
# ==============================================================================

class DataClassification(str, enum.Enum):
    """
    Institutional data sensitivity classifications.
    Hierarchy: PUBLIC (0) < INTERNAL (1) < CONFIDENTIAL (2) < RESTRICTED (3)
    """
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"

    @property
    def level(self) -> int:
        levels = {
            DataClassification.PUBLIC: 0,
            DataClassification.INTERNAL: 1,
            DataClassification.CONFIDENTIAL: 2,
            DataClassification.RESTRICTED: 3,
        }
        return levels[self]

    def can_access(self, required_classification: "DataClassification") -> bool:
        """Returns True if this clearance level is sufficient to access required classification."""
        return self.level >= required_classification.level


class SecurityViolationType(str, enum.Enum):
    """Catalog of GenAI security violation categories (OWASP Top 10 for LLMs)."""
    # Input threats
    DIRECT_PROMPT_INJECTION = "DIRECT_PROMPT_INJECTION"
    MALICIOUS_INSTRUCTION = "MALICIOUS_INSTRUCTION"
    EXCESSIVE_INPUT_SIZE = "EXCESSIVE_INPUT_SIZE"
    SENSITIVE_DATA_EXPOSURE = "SENSITIVE_DATA_EXPOSURE"
    SYSTEM_PROMPT_EXTRACTION = "SYSTEM_PROMPT_EXTRACTION"

    # Retrieval threats
    INDIRECT_PROMPT_INJECTION = "INDIRECT_PROMPT_INJECTION"
    CONTEXT_POISONING = "CONTEXT_POISONING"
    CROSS_TENANT_BREACH = "CROSS_TENANT_BREACH"
    UNAUTHORIZED_DOCUMENT_ACCESS = "UNAUTHORIZED_DOCUMENT_ACCESS"
    UNTRUSTED_SOURCE = "UNTRUSTED_SOURCE"
    CLASSIFICATION_CLEARANCE_VIOLATION = "CLASSIFICATION_CLEARANCE_VIOLATION"

    # Agent threats
    TOOL_ALLOWLIST_VIOLATION = "TOOL_ALLOWLIST_VIOLATION"
    TOOL_AUTHORIZATION_VIOLATION = "TOOL_AUTHORIZATION_VIOLATION"
    ITERATION_LIMIT_EXCEEDED = "ITERATION_LIMIT_EXCEEDED"
    TOOL_CALL_LIMIT_EXCEEDED = "TOOL_CALL_LIMIT_EXCEEDED"
    COST_BUDGET_EXCEEDED = "COST_BUDGET_EXCEEDED"
    TIME_BUDGET_EXCEEDED = "TIME_BUDGET_EXCEEDED"
    EXCESSIVE_AGENCY = "EXCESSIVE_AGENCY"

    # Output threats
    HALLUCINATED_EVIDENCE = "HALLUCINATED_EVIDENCE"
    INVALID_CITATION = "INVALID_CITATION"
    REGULATORY_POLICY_VIOLATION = "REGULATORY_POLICY_VIOLATION"
    UNSAFE_FINANCIAL_RECOMMENDATION = "UNSAFE_FINANCIAL_RECOMMENDATION"
    DATA_EXFILTRATION_ATTEMPT = "DATA_EXFILTRATION_ATTEMPT"


class SeverityLevel(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


# ==============================================================================
# Security Violation Records & Evaluation Results
# ==============================================================================

class SecurityViolation(BaseModel):
    """Detailed record of an individual security guardrail breach."""
    violation_type: SecurityViolationType
    severity: SeverityLevel = SeverityLevel.HIGH
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    sanitized_snippet: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class InputSecurityResult(BaseModel):
    """Result of multi-layered input perimeter validation."""
    is_safe: bool = True
    original_prompt: str
    sanitized_prompt: str
    violations: list[SecurityViolation] = Field(default_factory=list)
    detected_pii: list[dict[str, Any]] = Field(default_factory=list)
    detected_secrets: list[str] = Field(default_factory=list)
    input_length: int = 0
    estimated_tokens: int = 0


class DocumentSourceMetadata(BaseModel):
    """Metadata describing a retrieved document's origin and security classification."""
    document_id: str
    tenant_id: str
    source_uri: str
    source_name: str
    classification: DataClassification = DataClassification.INTERNAL
    required_permissions: list[str] = Field(default_factory=list)
    sha256_hash: str | None = None
    is_trusted_origin: bool = True


class RetrievalSecurityResult(BaseModel):
    """Result of post-retrieval security inspection and clearance enforcement."""
    is_safe: bool = True
    allowed_chunks: list[dict[str, Any]] = Field(default_factory=list)
    quarantined_chunks: list[dict[str, Any]] = Field(default_factory=list)
    violations: list[SecurityViolation] = Field(default_factory=list)
    tenant_mismatches_blocked: int = 0
    poisoned_chunks_blocked: int = 0
    clearance_failures_blocked: int = 0


class AgentSecurityState(BaseModel):
    """Tracks runtime governance parameters and budgets for an active agent run."""
    agent_id: str
    tenant_id: str
    current_iterations: int = 0
    max_iterations: int = 10
    tool_calls_count: int = 0
    max_tool_calls: int = 15
    accumulated_cost_usd: float = 0.0
    cost_budget_usd: float = 1.0
    elapsed_time_seconds: float = 0.0
    time_budget_seconds: float = 60.0
    tool_invocations: list[str] = Field(default_factory=list)


class AgentSecurityResult(BaseModel):
    """Result of agent action authorization and budget checks."""
    is_permitted: bool = True
    violations: list[SecurityViolation] = Field(default_factory=list)
    budget_exhausted: bool = False
    requires_human_approval: bool = False
    approval_reason: str | None = None


class OutputSecurityResult(BaseModel):
    """Result of synthesized output verification (grounding, citations, policy, safety)."""
    is_safe: bool = True
    original_output: str
    sanitized_output: str
    violations: list[SecurityViolation] = Field(default_factory=list)
    verified_citations: list[dict[str, Any]] = Field(default_factory=list)
    invalid_citations: list[dict[str, Any]] = Field(default_factory=list)
    hallucination_detected: bool = False
    financial_disclaimer_appended: bool = False
