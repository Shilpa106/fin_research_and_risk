import re
from typing import Any

from .models import (
    OutputSecurityResult,
    SecurityViolation,
    SecurityViolationType,
    SeverityLevel,
)

# Unsafe Financial Recommendation Signatures
UNSAFE_RECOMMENDATION_PATTERNS: list[tuple[str, str, SeverityLevel]] = [
    (
        r"(?i)\b(guaranteed\s+(returns?|profits?|yields?|gains?)|100%\s+guaranteed|(zero\s+risk|risk-?free)\s*(returns?|profits?|yields?|investments?)?)\b",
        "Illegal guaranteed financial return claim",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\b(insider\s+(tip|information|leak)|material\s+non-?public\s+information|mnpi|front-?run\s+(the\s+)?trade)\b",
        "Potential insider trading or MNPI solicitation/assertion",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\b(evade\s+(taxes|reporting|aml)|circumvent\s+(regulations|compliance|limits)|hide\s+(assets|funds)\s+offshore)\b",
        "Unlawful financial conduct / regulatory circumvention",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\b(pump\s+and\s+dump|artificially\s+inflate|manipulate\s+the\s+price)\b",
        "Market manipulation terminology detected",
        SeverityLevel.CRITICAL,
    ),
]

# Sensitive credentials & PII patterns to prevent Data Exfiltration
EXFILTRATION_PATTERNS: list[tuple[str, str]] = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
    (r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b", "[REDACTED_CREDIT_CARD]"),
    (r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED_AWS_KEY]"),
    (r"\b(sk-[a-zA-Z0-9]{20,}|sk-proj-[a-zA-Z0-9-_]{20,})\b", "[REDACTED_API_KEY]"),
    (r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b", "[REDACTED_JWT]"),
    (r"-----BEGIN (?:RSA|EC|DSA|OPENSSH)?\s*PRIVATE KEY-----[\s\S]*?-----END (?:RSA|EC|DSA|OPENSSH)?\s*PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
]

MANDATORY_DISCLAIMER: str = (
    "\n\n---\n**Regulatory Disclaimer**: This report is prepared solely for institutional research "
    "and risk assessment purposes and does not constitute financial, investment, or legal advice. "
    "Past performance is not indicative of future results."
)


class OutputSecurityGuard:
    """
    Enterprise Output Verification & Compliance Guard.
    Executes pre-response verification on synthesized agent outputs:
    1. Hallucination & grounding validation against evidence
    2. Citation validity checking (detects ghost/fabricated citations)
    3. Mandatory financial regulatory disclaimer enforcement
    4. Data exfiltration defense (redacts PII & credentials)
    5. Unsafe financial recommendation detection
    """

    def __init__(
        self,
        enforce_disclaimer: bool = True,
        hallucination_threshold: float = 0.5,
    ):
        self.enforce_disclaimer = enforce_disclaimer
        self.hallucination_threshold = hallucination_threshold

    def validate_output(
        self,
        output_text: str,
        retrieved_chunks: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> OutputSecurityResult:
        """
        Runs comprehensive security and regulatory validation on synthesized output.
        """
        violations: list[SecurityViolation] = []
        sanitized_output = output_text
        retrieved_chunks = retrieved_chunks or []
        tool_results = tool_results or []

        # ----------------------------------------------------------------------
        # 1. Unsafe Financial Recommendation Detection
        # ----------------------------------------------------------------------
        for pattern, desc, severity in UNSAFE_RECOMMENDATION_PATTERNS:
            match = re.search(pattern, sanitized_output)
            if match:
                violations.append(
                    SecurityViolation(
                        violation_type=SecurityViolationType.UNSAFE_FINANCIAL_RECOMMENDATION,
                        severity=severity,
                        message=f"Unsafe financial advisory violation: {desc}",
                        details={"pattern": pattern, "snippet": match.group(0)},
                        sanitized_snippet=match.group(0),
                    )
                )

        # ----------------------------------------------------------------------
        # 2. Data Exfiltration Defense (PII & Secret Leaks)
        # ----------------------------------------------------------------------
        for pattern, placeholder in EXFILTRATION_PATTERNS:
            matches = list(re.finditer(pattern, sanitized_output))
            if matches:
                violations.append(
                    SecurityViolation(
                        violation_type=SecurityViolationType.DATA_EXFILTRATION_ATTEMPT,
                        severity=SeverityLevel.CRITICAL,
                        message="Potential sensitive data exfiltration detected in synthesized output.",
                        details={"matches_count": len(matches)},
                    )
                )
                sanitized_output = re.sub(pattern, placeholder, sanitized_output)

        # ----------------------------------------------------------------------
        # 3. Citation Validation
        # ----------------------------------------------------------------------
        verified_citations, invalid_citations, citation_violations = self._validate_citations(
            output_text=sanitized_output,
            retrieved_chunks=retrieved_chunks,
        )
        violations.extend(citation_violations)

        # ----------------------------------------------------------------------
        # 4. Hallucination / Evidence Grounding Check
        # ----------------------------------------------------------------------
        hallucination_detected, grounding_violations = self._check_grounding(
            output_text=sanitized_output,
            retrieved_chunks=retrieved_chunks,
            tool_results=tool_results,
        )
        violations.extend(grounding_violations)

        # ----------------------------------------------------------------------
        # 5. Regulatory Policy Compliance (Mandatory Disclaimer)
        # ----------------------------------------------------------------------
        disclaimer_appended = False
        if self.enforce_disclaimer:
            has_disclaimer = any(
                phrase in sanitized_output.lower()
                for phrase in ["regulatory disclaimer", "does not constitute financial", "past performance is not"]
            )
            if not has_disclaimer:
                sanitized_output += MANDATORY_DISCLAIMER
                disclaimer_appended = True

        has_critical = any(v.severity == SeverityLevel.CRITICAL for v in violations)
        is_safe = not has_critical

        return OutputSecurityResult(
            is_safe=is_safe,
            original_output=output_text,
            sanitized_output=sanitized_output,
            violations=violations,
            verified_citations=verified_citations,
            invalid_citations=invalid_citations,
            hallucination_detected=hallucination_detected,
            financial_disclaimer_appended=disclaimer_appended,
        )

    def _validate_citations(
        self,
        output_text: str,
        retrieved_chunks: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[SecurityViolation]]:
        """
        Parses citation references [Doc: ..., Page: ...] or [Citation: ...]
        and cross-references with retrieved chunk IDs/sources.
        """
        verified: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []
        violations: list[SecurityViolation] = []

        valid_doc_ids: set[str] = set()
        for chunk in retrieved_chunks:
            if "document_id" in chunk:
                valid_doc_ids.add(str(chunk["document_id"]))
            if "chunk_id" in chunk:
                valid_doc_ids.add(str(chunk["chunk_id"]))
            if "id" in chunk:
                valid_doc_ids.add(str(chunk["id"]))

        # Match citations like [Doc: AAPL-10K, Page: 12] or [Citation: AAPL-10K]
        citation_regex = r"\[(?:Doc|Citation|Source):\s*([^,\]]+)(?:,\s*Page:\s*(\d+))?\]"
        matches = list(re.finditer(citation_regex, output_text, re.IGNORECASE))

        for m in matches:
            doc_ref = m.group(1).strip()
            page_ref = m.group(2)
            citation_item = {"doc_ref": doc_ref, "page": page_ref, "raw": m.group(0)}

            if valid_doc_ids and doc_ref not in valid_doc_ids:
                invalid.append(citation_item)
                violations.append(
                    SecurityViolation(
                        violation_type=SecurityViolationType.INVALID_CITATION,
                        severity=SeverityLevel.HIGH,
                        message=f"Ghost citation detected: '{doc_ref}' was not in the retrieved context.",
                        details=citation_item,
                    )
                )
            else:
                verified.append(citation_item)

        return verified, invalid, violations

    def _check_grounding(
        self,
        output_text: str,
        retrieved_chunks: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
    ) -> tuple[bool, list[SecurityViolation]]:
        """
        Extracts key numerical claims from response and verifies whether they appear in evidence.
        """
        violations: list[SecurityViolation] = []
        hallucination_detected = False

        # Build concatenated evidence text
        evidence_corpus = " ".join([
            str(c.get("content", c.get("text", ""))) for c in retrieved_chunks
        ] + [str(t) for t in tool_results])

        if not evidence_corpus.strip():
            return False, violations

        # Regex for financial metrics / percentages / currency numbers (e.g., $142.50, 18.4%, 250M)
        metric_regex = r"(\$\d+(?:\.\d+)?(?:\s*[MBKmbk])?|\b\d+(?:\.\d+)?%)"
        metrics_in_output = re.findall(metric_regex, output_text)

        unsupported_metrics: list[str] = []
        for metric in metrics_in_output:
            # Clean dollar/percent symbols for search
            cleaned = metric.replace("$", "").replace("%", "").strip()
            if cleaned not in evidence_corpus:
                unsupported_metrics.append(metric)

        # If more than 50% of specific metrics are ungrounded and at least 2 are missing
        if len(unsupported_metrics) >= 2 and len(unsupported_metrics) / len(metrics_in_output) > self.hallucination_threshold:
            hallucination_detected = True
            violations.append(
                SecurityViolation(
                    violation_type=SecurityViolationType.HALLUCINATED_EVIDENCE,
                    severity=SeverityLevel.HIGH,
                    message="Ungrounded financial metrics detected in output (potential hallucination).",
                    details={"unsupported_metrics": unsupported_metrics},
                )
            )

        return hallucination_detected, violations
