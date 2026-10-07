import hashlib
import re
from typing import Any

from ...domain.entities import RoleType
from ...security.context import RequestSecurityContext
from .models import (
    DataClassification,
    RetrievalSecurityResult,
    SecurityViolation,
    SecurityViolationType,
    SeverityLevel,
)

# Role to DataClassification clearance mapping
ROLE_CLEARANCE_MAP: dict[RoleType, DataClassification] = {
    RoleType.READ_ONLY_USER: DataClassification.INTERNAL,
    RoleType.ANALYST: DataClassification.CONFIDENTIAL,
    RoleType.ADVISOR: DataClassification.CONFIDENTIAL,
    RoleType.RISK_MANAGER: DataClassification.RESTRICTED,
    RoleType.ADMIN: DataClassification.RESTRICTED,
}

# Indirect Prompt Injection & Context Poisoning Signatures in Ingested Content
INDIRECT_INJECTION_PATTERNS: list[tuple[str, str, SeverityLevel]] = [
    (
        r"(?i)\b(ignore|disregard)\s+(all\s+)?(prior|previous|system|above)\s+(instructions|directives|prompts|context)\b",
        "Indirect override instruction in retrieved chunk",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\b(system\s+note\s*:|developer\s+instruction\s*:|assistant\s+override\s*:)\b",
        "Authoritative system note injection in retrieved document",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\b(instruct\s+the\s+(agent|model|assistant)\s+to|tell\s+the\s+user\s+that)\b",
        "Agent behavior redirection attempt in retrieved text",
        SeverityLevel.HIGH,
    ),
    (
        r"(?i)!\[.*?\]\((https?://[^\s)]+/[^\s)]*(\?|&)?[^\s)]*)\)",
        "Markdown image exfiltration payload in retrieved document",
        SeverityLevel.CRITICAL,
    ),
    (
        r"<!--[\s\S]*?(ignore|override|system|secret)[\s\S]*?-->",
        "Hidden HTML comment injection payload",
        SeverityLevel.HIGH,
    ),
    (
        r"[\u200B\u200C\u200D\uFEFF]{3,}",
        "Zero-width character steganography / context poisoning",
        SeverityLevel.HIGH,
    ),
]

TRUSTED_DOMAINS: set[str] = {
    "sec.gov",
    "bloomberg.com",
    "reuters.com",
    "federalreserve.gov",
    "internal.bank.net",
    "enterprise-fin.s3.amazonaws.com",
}


class RetrievalSecurityGuard:
    """
    Enterprise Retrieval Security & Context Sanitization Guard.
    Executes post-retrieval verification across candidate chunks before context construction:
    1. Multi-tenant isolation verification
    2. Document-level RBAC and permission checking
    3. Document classification clearance enforcement
    4. Source origin & trust validation
    5. Indirect prompt injection & context poisoning scanning
    """

    def __init__(
        self,
        trusted_domains: set[str] | None = None,
        enforce_integrity_hash: bool = False,
    ):
        self.trusted_domains = trusted_domains or TRUSTED_DOMAINS
        self.enforce_integrity_hash = enforce_integrity_hash

    def evaluate_retrieved_chunks(
        self,
        chunks: list[dict[str, Any]],
        context: RequestSecurityContext,
    ) -> RetrievalSecurityResult:
        """
        Filters and validates candidate retrieved chunks against security policies.
        Quarantines malicious, cross-tenant, or clearance-violating chunks.
        """
        allowed_chunks: list[dict[str, Any]] = []
        quarantined_chunks: list[dict[str, Any]] = []
        violations: list[SecurityViolation] = []

        tenant_mismatches = 0
        poisoned_count = 0
        clearance_failures = 0

        # Determine caller's maximum clearance based on active roles
        user_max_clearance = self._resolve_user_clearance(context.roles)

        for chunk in chunks:
            chunk_tenant = chunk.get("tenant_id")
            chunk_id = chunk.get("chunk_id", chunk.get("id", "unknown-chunk"))
            text = chunk.get("content", chunk.get("text", ""))

            # ------------------------------------------------------------------
            # 1. Multi-Tenant Isolation Check
            # ------------------------------------------------------------------
            if not chunk_tenant or chunk_tenant != context.tenant_id:
                tenant_mismatches += 1
                violation = SecurityViolation(
                    violation_type=SecurityViolationType.CROSS_TENANT_BREACH,
                    severity=SeverityLevel.CRITICAL,
                    message=f"Cross-tenant retrieval blocked: Chunk belongs to '{chunk_tenant}', caller is '{context.tenant_id}'.",
                    details={"chunk_id": chunk_id, "chunk_tenant": chunk_tenant, "caller_tenant": context.tenant_id},
                )
                violations.append(violation)
                quarantined_chunks.append({**chunk, "quarantine_reason": "CROSS_TENANT_BREACH"})
                continue

            # ------------------------------------------------------------------
            # 2. Classification Clearance Check
            # ------------------------------------------------------------------
            classification_str = chunk.get("classification", DataClassification.INTERNAL.value)
            try:
                chunk_classification = DataClassification(classification_str.upper())
            except (ValueError, AttributeError):
                chunk_classification = DataClassification.INTERNAL

            if not user_max_clearance.can_access(chunk_classification):
                clearance_failures += 1
                violation = SecurityViolation(
                    violation_type=SecurityViolationType.CLASSIFICATION_CLEARANCE_VIOLATION,
                    severity=SeverityLevel.HIGH,
                    message=(
                        f"Access denied: Document classification '{chunk_classification.value}' "
                        f"exceeds user clearance '{user_max_clearance.value}'."
                    ),
                    details={
                        "chunk_id": chunk_id,
                        "required_classification": chunk_classification.value,
                        "user_clearance": user_max_clearance.value,
                    },
                )
                violations.append(violation)
                quarantined_chunks.append({**chunk, "quarantine_reason": "CLEARANCE_DEFICIENT"})
                continue

            # ------------------------------------------------------------------
            # 3. Document-Level Permission Filtering
            # ------------------------------------------------------------------
            required_perms = chunk.get("permissions") or chunk.get("required_permissions") or []
            if isinstance(required_perms, str):
                required_perms = [required_perms]
            if required_perms:
                has_perm = any(context.has_permission(p) for p in required_perms)
                # Admins bypass specific permission tags
                if not has_perm and RoleType.ADMIN not in context.roles:
                    violation = SecurityViolation(
                        violation_type=SecurityViolationType.UNAUTHORIZED_DOCUMENT_ACCESS,
                        severity=SeverityLevel.HIGH,
                        message=f"Access denied: User lacks permissions {required_perms} for chunk '{chunk_id}'.",
                        details={"chunk_id": chunk_id, "required_permissions": required_perms},
                    )
                    violations.append(violation)
                    quarantined_chunks.append({**chunk, "quarantine_reason": "MISSING_DOCUMENT_PERMISSION"})
                    continue

            # ------------------------------------------------------------------
            # 4. Source Trust & Integrity Validation
            # ------------------------------------------------------------------
            source_uri = chunk.get("source", chunk.get("source_uri", ""))
            if source_uri and not self._is_source_trusted(source_uri):
                violation = SecurityViolation(
                    violation_type=SecurityViolationType.UNTRUSTED_SOURCE,
                    severity=SeverityLevel.MEDIUM,
                    message=f"Untrusted document source '{source_uri}' detected.",
                    details={"chunk_id": chunk_id, "source_uri": source_uri},
                )
                violations.append(violation)
                quarantined_chunks.append({**chunk, "quarantine_reason": "UNTRUSTED_SOURCE"})
                continue

            # Checksum / Tamper verification if provided
            expected_hash = chunk.get("sha256_hash")
            if expected_hash:
                actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if actual_hash != expected_hash:
                    poisoned_count += 1
                    violation = SecurityViolation(
                        violation_type=SecurityViolationType.CONTEXT_POISONING,
                        severity=SeverityLevel.CRITICAL,
                        message=f"Integrity check failed: Chunk '{chunk_id}' hash mismatch (possible tampering).",
                        details={"chunk_id": chunk_id, "expected": expected_hash, "actual": actual_hash},
                    )
                    violations.append(violation)
                    quarantined_chunks.append({**chunk, "quarantine_reason": "HASH_INTEGRITY_FAILED"})
                    continue

            # ------------------------------------------------------------------
            # 5. Indirect Prompt Injection & Context Poisoning Scanner
            # ------------------------------------------------------------------
            injection_detected = False
            for pattern, desc, severity in INDIRECT_INJECTION_PATTERNS:
                match = re.search(pattern, text)
                if match:
                    poisoned_count += 1
                    injection_detected = True
                    violation = SecurityViolation(
                        violation_type=SecurityViolationType.INDIRECT_PROMPT_INJECTION,
                        severity=severity,
                        message=f"Context poisoning / indirect injection detected in chunk '{chunk_id}': {desc}",
                        details={"chunk_id": chunk_id, "pattern": pattern, "snippet": match.group(0)},
                        sanitized_snippet=match.group(0),
                    )
                    violations.append(violation)
                    quarantined_chunks.append({**chunk, "quarantine_reason": "INDIRECT_PROMPT_INJECTION"})
                    break

            if injection_detected:
                continue

            # Chunk passed all retrieval security gates
            allowed_chunks.append(chunk)

        is_safe = (tenant_mismatches == 0 and poisoned_count == 0)

        return RetrievalSecurityResult(
            is_safe=is_safe,
            allowed_chunks=allowed_chunks,
            quarantined_chunks=quarantined_chunks,
            violations=violations,
            tenant_mismatches_blocked=tenant_mismatches,
            poisoned_chunks_blocked=poisoned_count,
            clearance_failures_blocked=clearance_failures,
        )

    def _resolve_user_clearance(self, roles: list[RoleType]) -> DataClassification:
        """Computes the user's highest data clearance level across their assigned roles."""
        max_level = DataClassification.PUBLIC
        for role in roles:
            role_clearance = ROLE_CLEARANCE_MAP.get(role, DataClassification.PUBLIC)
            if role_clearance.level > max_level.level:
                max_level = role_clearance
        return max_level

    def _is_source_trusted(self, source_uri: str) -> bool:
        """Validates whether source origin belongs to approved institutional domains or schemas."""
        lower_uri = source_uri.lower()
        # Internal scheme or relative document path
        if lower_uri.startswith(("internal://", "s3://enterprise-", "edgar://")):
            return True
        for domain in self.trusted_domains:
            if domain in lower_uri:
                return True
        return False
