import base64
import binascii
import re
from typing import Any

from .models import (
    InputSecurityResult,
    SecurityViolation,
    SecurityViolationType,
    SeverityLevel,
)

# ==============================================================================
# Detection Signatures & Regex Patterns
# ==============================================================================

DIRECT_INJECTION_PATTERNS: list[tuple[str, str, SeverityLevel]] = [
    (
        r"(?i)\bignore\s+(all\s+)?(previous|prior|above|system)\s+(instructions|directives|prompts|rules)\b",
        "Classic instruction override / prompt injection attempt",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\bdisregard\s+(all\s+)?(previous|prior|system)\s+(instructions|directives|guidelines)\b",
        "Directive override attempt",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\byou\s+are\s+now\s+(an?\s+)?(unrestricted|dan|jailbroken|unfiltered|evil|chaos)\b",
        "DAN / Unrestricted persona hijacking attempt",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\b(dan\s+mode|jailbreak\s+mode|do\s+anything\s+now|developer\s+mode\s+enabled)\b",
        "Jailbreak mode keyword activation",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)(<\|im_start\|>system|<\|im_end\|>|\[INST\]\s*<<SYS>>|<<<SYSTEM>>>|---BEGIN SYSTEM PROMPT---)",
        "Control token / system delimiter injection attempt",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\bbypass\s+(all\s+)?(guardrails|filters|safety\s+checks|security\s+rules|restrictions)\b",
        "Explicit guardrail bypass command",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\b(system\s+directive\s*:|admin\s+override\s*:|kernel\s+override\s*:)\b",
        "Fake authoritative system directive prefix",
        SeverityLevel.HIGH,
    ),
    (
        r"(?i)\b(pretend\s+you\s+have\s+no\s+(morals|rules|restrictions|filters))\b",
        "Roleplay filter removal attempt",
        SeverityLevel.HIGH,
    ),
]

MALICIOUS_INSTRUCTION_PATTERNS: list[tuple[str, str, SeverityLevel]] = [
    (
        r"(?i)\b(print|dump|show|output|reveal|repeat)\s+(your\s+)?(entire\s+)?(system\s+prompt|initial\s+instructions|system\s+instructions|pre-prompt)\b",
        "System prompt extraction attack",
        SeverityLevel.HIGH,
    ),
    (
        r"(?i)\b(repeat\s+everything\s+above\s+verbatim|output\s+all\s+text\s+before\s+this\s+prompt)\b",
        "Context extraction attack",
        SeverityLevel.HIGH,
    ),
    (
        r"(?i)\b(grant\s+me\s+admin|elevate\s+(my\s+)?privileges?|become\s+super-?user|sudo\s+exec)\b",
        "Privilege escalation instruction",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\b(override\s+tenant_id|disable\s+tenant\s+isolation|bypass\s+rls)\b",
        "Tenant isolation subversion attempt",
        SeverityLevel.CRITICAL,
    ),
    (
        r"(?i)\b(execute\s+shell|run\s+terminal\s+command|subprocess\.Popen|os\.system|eval\(|exec\()\b",
        "Remote code execution / shell invocation attempt",
        SeverityLevel.CRITICAL,
    ),
]

SENSITIVE_DATA_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, entity_type, replacement_label)
    (
        r"\b\d{3}-\d{2}-\d{4}\b",
        "SSN",
        "[REDACTED_SSN]",
    ),
    (
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b",
        "CREDIT_CARD",
        "[REDACTED_CREDIT_CARD]",
    ),
    (
        r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]?){0,16}\b",
        "IBAN",
        "[REDACTED_IBAN]",
    ),
    (
        r"\bAKIA[0-9A-Z]{16}\b",
        "AWS_ACCESS_KEY",
        "[REDACTED_AWS_KEY]",
    ),
    (
        r"\b(sk-[a-zA-Z0-9]{20,}|sk-proj-[a-zA-Z0-9-_]{20,})\b",
        "OPENAI_API_KEY",
        "[REDACTED_API_KEY]",
    ),
    (
        r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b",
        "JWT_TOKEN",
        "[REDACTED_JWT]",
    ),
    (
        r"-----BEGIN (?:RSA|EC|DSA|OPENSSH)?\s*PRIVATE KEY-----[\s\S]*?-----END (?:RSA|EC|DSA|OPENSSH)?\s*PRIVATE KEY-----",
        "PRIVATE_KEY",
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "EMAIL",
        "[REDACTED_EMAIL]",
    ),
    (
        r"\b(?:\+?1[-. ]?)?\(?[2-9]\d{2}\)?[-. ]?\d{3}[-. ]?\d{4}\b",
        "PHONE_NUMBER",
        "[REDACTED_PHONE]",
    ),
]


class InputSecurityGuard:
    """
    Enterprise GenAI Input Security Perimeter Guard.
    Enforces multi-layer screening before user queries reach the LLM or Agent planner:
    1. Direct prompt injection & jailbreak detection
    2. Malicious instruction & system extraction detection
    3. Obfuscated / Base64 encoded payload detection
    4. Input size & token threshold defense
    5. PII & Secret credential detection with automated institutional redaction
    """

    def __init__(
        self,
        max_characters: int = 10000,
        max_tokens: int = 2500,
        redact_pii: bool = True,
        block_on_critical: bool = True,
    ):
        self.max_characters = max_characters
        self.max_tokens = max_tokens
        self.redact_pii = redact_pii
        self.block_on_critical = block_on_critical

    def validate_input(self, prompt: str, user_id: str | None = None) -> InputSecurityResult:
        """
        Runs comprehensive security evaluation across user input prompt.
        Returns InputSecurityResult with safety flag, detected violations, and sanitized prompt.
        """
        violations: list[SecurityViolation] = []
        detected_pii: list[dict[str, Any]] = []
        detected_secrets: list[str] = []

        char_len = len(prompt)
        estimated_tokens = char_len // 4  # standard conservative 4 char/token rule

        # ----------------------------------------------------------------------
        # 1. Excessive Input Size Check
        # ----------------------------------------------------------------------
        if char_len > self.max_characters or estimated_tokens > self.max_tokens:
            violations.append(
                SecurityViolation(
                    violation_type=SecurityViolationType.EXCESSIVE_INPUT_SIZE,
                    severity=SeverityLevel.HIGH,
                    message=(
                        f"Input exceeds maximum allowed size ({char_len} chars > {self.max_characters} "
                        f"or ~{estimated_tokens} tokens > {self.max_tokens})."
                    ),
                    details={"char_length": char_len, "estimated_tokens": estimated_tokens},
                )
            )

        # ----------------------------------------------------------------------
        # 2. Direct Prompt Injection Detection
        # ----------------------------------------------------------------------
        for pattern, desc, severity in DIRECT_INJECTION_PATTERNS:
            match = re.search(pattern, prompt)
            if match:
                violations.append(
                    SecurityViolation(
                        violation_type=SecurityViolationType.DIRECT_PROMPT_INJECTION,
                        severity=severity,
                        message=f"Prompt injection detected: {desc}",
                        details={"matched_pattern": pattern, "snippet": match.group(0)},
                        sanitized_snippet=match.group(0),
                    )
                )

        # ----------------------------------------------------------------------
        # 3. Base64 / Obfuscated Payload Inspection
        # ----------------------------------------------------------------------
        obfuscated_violation = self._scan_base64_payloads(prompt)
        if obfuscated_violation:
            violations.append(obfuscated_violation)

        # ----------------------------------------------------------------------
        # 4. Malicious Instruction & Extraction Detection
        # ----------------------------------------------------------------------
        for pattern, desc, severity in MALICIOUS_INSTRUCTION_PATTERNS:
            match = re.search(pattern, prompt)
            if match:
                vtype = (
                    SecurityViolationType.SYSTEM_PROMPT_EXTRACTION
                    if "system prompt" in desc.lower() or "verbatim" in desc.lower()
                    else SecurityViolationType.MALICIOUS_INSTRUCTION
                )
                violations.append(
                    SecurityViolation(
                        violation_type=vtype,
                        severity=severity,
                        message=f"Malicious instruction detected: {desc}",
                        details={"matched_pattern": pattern, "snippet": match.group(0)},
                        sanitized_snippet=match.group(0),
                    )
                )

        # ----------------------------------------------------------------------
        # 5. Sensitive Information & Credential Detection / Redaction
        # ----------------------------------------------------------------------
        sanitized_prompt = prompt
        for pattern, entity_type, replacement in SENSITIVE_DATA_PATTERNS:
            matches = list(re.finditer(pattern, sanitized_prompt))
            if matches:
                is_secret = entity_type in {"AWS_ACCESS_KEY", "OPENAI_API_KEY", "JWT_TOKEN", "PRIVATE_KEY"}
                for m in matches:
                    matched_str = m.group(0)
                    if is_secret:
                        detected_secrets.append(entity_type)
                        violations.append(
                            SecurityViolation(
                                violation_type=SecurityViolationType.SENSITIVE_DATA_EXPOSURE,
                                severity=SeverityLevel.CRITICAL,
                                message=f"Secret / Credential exposure detected ({entity_type}).",
                                details={"entity_type": entity_type},
                            )
                        )
                    else:
                        detected_pii.append({"type": entity_type, "value_masked": f"{matched_str[:2]}***{matched_str[-2:]}"})
                        violations.append(
                            SecurityViolation(
                                violation_type=SecurityViolationType.SENSITIVE_DATA_EXPOSURE,
                                severity=SeverityLevel.HIGH,
                                message=f"PII detected in input ({entity_type}).",
                                details={"entity_type": entity_type},
                            )
                        )

                if self.redact_pii:
                    sanitized_prompt = re.sub(pattern, replacement, sanitized_prompt)

        # Determine overall safety
        has_critical = any(v.severity == SeverityLevel.CRITICAL for v in violations)
        has_high_injection = any(
            v.violation_type in {
                SecurityViolationType.DIRECT_PROMPT_INJECTION,
                SecurityViolationType.MALICIOUS_INSTRUCTION,
                SecurityViolationType.SYSTEM_PROMPT_EXTRACTION,
                SecurityViolationType.EXCESSIVE_INPUT_SIZE,
            }
            for v in violations
        )

        is_safe = True
        if self.block_on_critical and (has_critical or has_high_injection):
            is_safe = False

        return InputSecurityResult(
            is_safe=is_safe,
            original_prompt=prompt,
            sanitized_prompt=sanitized_prompt,
            violations=violations,
            detected_pii=detected_pii,
            detected_secrets=detected_secrets,
            input_length=char_len,
            estimated_tokens=estimated_tokens,
        )

    def _scan_base64_payloads(self, prompt: str) -> SecurityViolation | None:
        """Inspects potential base64 strings to thwart obfuscated prompt injection."""
        base64_candidate_regex = r"(?:[A-Za-z0-9+/]{4}){3,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?"
        candidates = re.findall(base64_candidate_regex, prompt)
        for candidate in candidates:
            try:
                decoded = base64.b64decode(candidate, validate=True).decode("utf-8", errors="ignore")
                for pattern, desc, _ in DIRECT_INJECTION_PATTERNS:
                    if re.search(pattern, decoded):
                        return SecurityViolation(
                            violation_type=SecurityViolationType.DIRECT_PROMPT_INJECTION,
                            severity=SeverityLevel.CRITICAL,
                            message=f"Obfuscated / Base64 encoded prompt injection detected: {desc}",
                            details={"encoded_payload": candidate[:24] + "...", "decoded_snippet": decoded[:64]},
                        )
            except (binascii.Error, ValueError):
                continue
        return None
