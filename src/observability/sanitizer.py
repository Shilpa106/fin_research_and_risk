import re
from typing import Any

# ==============================================================================
# Enterprise Security & Privacy Scrubbing Patterns
# ZERO LEAKAGE POLICY: Never log secrets, credentials, or sensitive financial data.
# ==============================================================================

# 1. Credentials & Secrets
BEARER_TOKEN_REGEX = re.compile(r"(Bearer\s+)[A-Za-z0-9\-_\.=]+", re.IGNORECASE)
JWT_REGEX = re.compile(r"eyJ[A-Za-z0-9\-_=]+\.eyJ[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_.+/=]*")
AWS_KEY_REGEX = re.compile(r"(AKIA[0-9A-Z]{16})")
GENERIC_SECRET_REGEX = re.compile(
    r'(?i)(api[_-]?key|secret[_-]?key|access[_-]?key|private[_-]?key|secret|password|passwd|pwd|token|authorization|auth_token)["\']?\s*[:=]\s*["\']?([^"\'\s,;]+)["\']?'
)

# 2. Sensitive Financial & Identity PII
# Credit card / Payment Card (13-19 digits, optionally spaced or hyphenated)
PAN_CARD_REGEX = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b|\b\d{15,16}\b")
# US Social Security Number (SSN: XXX-XX-XXXX)
SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# International Bank Account Number (IBAN)
IBAN_REGEX = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}\b")
# Routing / Swift Code followed by bank account numbers
BANK_ACCOUNT_REGEX = re.compile(r'(?i)(account[_-]?no|account[_-]?number|routing[_-]?number)["\']?\s*[:=]\s*["\']?(\d{6,17})["\']?')

SENSITIVE_KEY_NAMES = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "jwt_secret_key",
    "jwt_secret",
    "api_key",
    "x_api_key",
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "ssn",
    "social_security",
    "pan",
    "card_number",
    "credit_card",
    "cvv",
    "cvc",
    "bank_account",
    "iban",
    "routing_number",
}


def sanitize_text(text: str) -> str:
    """
    Applies comprehensive regex scrubbing to a text string.
    Replaces tokens, credentials, and financial PII with institutional redaction masks.
    """
    if not isinstance(text, str) or not text:
        return text

    # Scrub Bearer & JWT tokens
    text = BEARER_TOKEN_REGEX.sub(r"\1[REDACTED_BEARER_TOKEN]", text)
    text = JWT_REGEX.sub("[REDACTED_JWT]", text)
    # Scrub AWS access keys
    text = AWS_KEY_REGEX.sub("[REDACTED_AWS_KEY]", text)
    # Scrub Key-Value secrets
    text = GENERIC_SECRET_REGEX.sub(r'\1="[REDACTED_SECRET]"', text)
    # Scrub Payment Card Numbers (PAN)
    text = PAN_CARD_REGEX.sub("[REDACTED_PAN]", text)
    # Scrub Social Security Numbers (SSN)
    text = SSN_REGEX.sub("[REDACTED_SSN]", text)
    # Scrub IBANs
    text = IBAN_REGEX.sub("[REDACTED_IBAN]", text)
    # Scrub Bank Accounts
    text = BANK_ACCOUNT_REGEX.sub(r'\1="[REDACTED_ACCOUNT]"', text)

    return text


def sanitize_payload(payload: Any) -> Any:
    """
    Recursively scrubs dictionaries, lists, tuples, and primitive objects.
    Redacts keys matching sensitive names and applies pattern filters to string values.
    """
    if isinstance(payload, dict):
        sanitized_dict: dict[str, Any] = {}
        for k, v in payload.items():
            k_lower = str(k).lower()
            if any(sens in k_lower for sens in SENSITIVE_KEY_NAMES):
                sanitized_dict[k] = "[REDACTED_CREDENTIAL]"
            else:
                sanitized_dict[k] = sanitize_payload(v)
        return sanitized_dict

    elif isinstance(payload, list):
        return [sanitize_payload(item) for item in payload]

    elif isinstance(payload, tuple):
        return tuple(sanitize_payload(item) for item in payload)

    elif isinstance(payload, str):
        return sanitize_text(payload)

    return payload
